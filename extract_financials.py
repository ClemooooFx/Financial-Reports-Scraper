"""
Financial Statements Extractor (pdfplumber-only)
Extracts Balance Sheet, Income Statement, Cash Flow, and Equity Changes from PDF reports.
- Uses pdfplumber for all table and text extraction (no Camelot).
- Preserves full item/description text (merges multi-line labels).
- Dynamically infers numeric columns (years) and preserves rows as line items.
- Merges multi-page statements.
"""

import pdfplumber
import pandas as pd
import json
from pathlib import Path
import re
from datetime import datetime
import argparse
from typing import Dict, List, Optional
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinancialStatementsExtractor:
    def __init__(self, base_dir: str = "reports"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Statement title keywords (case-insensitive)
        self.statement_keywords = {
            'balance_sheet': [
                'statement of financial position',
                'balance sheet',
                'statement of assets',
                'consolidated statement of financial position'
            ],
            'income_statement': [
                'statement of profit or loss',
                'income statement',
                'statement of comprehensive income',
                'profit and loss',
                'statement of profit or loss and other comprehensive income',
                'consolidated statement of profit'
            ],
            'cash_flow': [
                'statement of cash flows',
                'cash flow statement',
                'consolidated statement of cash flows'
            ],
            'equity_changes': [
                'statement of changes in equity',
                'changes in equity',
                'consolidated statement of changes in equity'
            ]
        }

    # -------------------------
    # Utilities / heuristics
    # -------------------------
    def identify_statement_type(self, text: str) -> Optional[str]:
        """Identify which financial statement this page contains based on title keywords."""
        if not text:
            return None
        text_lower = text.lower()
        for statement_type, keywords in self.statement_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return statement_type
        return None

    def extract_units(self, text: str) -> Optional[str]:
        """Extract the unit of measurement from text (e.g., 'thousands', 'millions')."""
        if not text:
            return None
        patterns = [
            r"in\s+(\w+)\s+(?:kenya\s+)?shillings?",
            r"figures?\s+in\s+(\w+)",
            r"amounts?\s+in\s+(\w+)",
            r"\((?:kshs?\.?\s+)?[\'\"]?(\w+)[\'\"]?\)",
            r"shs\.?\s+[\'\"]?(\w+)[\'\"]?"
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                unit = match.group(1).lower()
                if 'thousand' in unit:
                    return 'thousands'
                if 'million' in unit:
                    return 'millions'
                if 'billion' in unit:
                    return 'billions'
                return unit
        return None

    def extract_table_title(self, text: str, statement_type: str) -> str:
        """Extract the exact table title from page text; prefer the matching line."""
        if not text:
            return self._default_title(statement_type)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        keywords = self.statement_keywords.get(statement_type, [])
        for i, line in enumerate(lines[:25]):  # only scan first 25 lines for title
            low = line.lower()
            for kw in keywords:
                if kw in low:
                    title = line
                    # attach adjacent short subtitle line if present (e.g., "as at 31 December 2020")
                    if i + 1 < len(lines):
                        nxt = lines[i + 1]
                        if len(nxt) < 80 and ('as at' in nxt.lower() or 'for the year' in nxt.lower() or re.search(r'20\d{2}', nxt)):
                            title = f"{title} — {nxt}"
                    return title
        return self._default_title(statement_type)

    def _default_title(self, statement_type: str) -> str:
        defaults = {
            'balance_sheet': 'Statement of Financial Position',
            'income_statement': 'Statement of Profit or Loss',
            'cash_flow': 'Statement of Cash Flows',
            'equity_changes': 'Statement of Changes in Equity'
        }
        return defaults.get(statement_type, 'Financial Statement')

    # -------------------------
    # Table cleaning & reconstruction (pdfplumber tables)
    # -------------------------
    def clean_table_data(self, table: List[List[str]]) -> Optional[pd.DataFrame]:
        """
        Clean raw pdfplumber table output.
        - Merges multiline cells (newlines inside cells)
        - Combines label columns into single 'item' column
        - Dynamically infers numeric columns (year/value columns)
        - Returns DataFrame with columns: ['item', 'col_1', 'col_2', ...]
        """
        if not table:
            return None

        df = pd.DataFrame(table).astype(str).replace(r'^\s*$', pd.NA, regex=True)

        # Drop empty rows & columns
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        df = df.reset_index(drop=True)
        if df.empty:
            return None

        # Normalize each cell: replace internal newlines with space and strip
        df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if pd.notna(x) else '')

        # Heuristic: identify which columns are primarily numeric vs textual
        numeric_cols = []
        text_cols = []
        for col in df.columns:
            sample = df[col].head(20).astype(str)
            # count numeric-like entries
            num_count = sample.str.contains(r'\d').sum()
            text_count = sample.str.contains(r'[A-Za-z]').sum()
            # if more numeric than text -> numeric column
            if num_count >= text_count and num_count > 0:
                numeric_cols.append(col)
            else:
                text_cols.append(col)

        # If no numeric columns detected, try alternative detection by searching for commas or parentheses or percent
        if not numeric_cols:
            for col in df.columns:
                sample = df[col].astype(str)
                if sample.str.contains(r'[,()\d%]').any():
                    if col not in numeric_cols:
                        numeric_cols.append(col)
                else:
                    if col not in text_cols:
                        text_cols.append(col)

        # Merge all text columns (labels) into one 'item' column
        if not text_cols:
            # if we failed to detect text columns, assume first column is item
            text_cols = [df.columns[0]]
            if len(df.columns) > 1:
                numeric_cols = [c for c in df.columns if c != df.columns[0]]

        df['item'] = df[text_cols].apply(lambda row: ' '.join([str(v).strip() for v in row if pd.notna(v) and str(v).strip() not in ['', '-']]), axis=1)

        # Create final DataFrame: item + numeric columns ordered left-to-right by original index
        ordered_numeric = [c for c in df.columns if c in numeric_cols]
        final_cols = ['item'] + ordered_numeric

        final_df = df[final_cols].copy()
        # Remove rows that have blank item and no numeric values
        def row_is_empty(r):
            item = str(r['item']).strip()
            nums = ''.join([str(r[c]) for c in ordered_numeric])
            return (item == '') and (not re.search(r'\d', nums))
        final_df = final_df[~final_df.apply(row_is_empty, axis=1)]

        final_df = final_df.reset_index(drop=True)
        if final_df.empty:
            return None
        return final_df

    # -------------------------
    # Extraction main loop using pdfplumber-only
    # -------------------------
    def extract_statement_from_pdf(self, pdf_path: Path) -> Optional[Dict]:
        """
        Extract statements from a PDF using pdfplumber.
        Returns a dict with statement types mapping to {tables, title, units, pages}
        """
        statements = {
            'balance_sheet': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'income_statement': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'cash_flow': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'equity_changes': {'tables': [], 'title': None, 'units': None, 'pages': []}
        }

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # We'll keep track of the last-seen statement_type to allow multi-page continuation
                current_statement = None

                for page_num, page in enumerate(pdf.pages, start=1):
                    try:
                        page_text = page.extract_text() or ""
                        # Identify page-level statement type first
                        page_statement = self.identify_statement_type(page_text)

                        # If page contains a statement title use it; else if we were already inside a statement, continue
                        if page_statement:
                            current_statement = page_statement

                        if not current_statement:
                            # Nothing to extract on this page
                            continue

                        # Extract tables from the page. pdfplumber returns list of tables (list of row lists)
                        raw_tables = page.extract_tables()
                        if not raw_tables:
                            # Fallback: try extracting table-like blocks via extract_table with explicit settings
                            # (some PDFs require specifying explicit settings, but keep default for now)
                            continue

                        # Set title and units the first time we see this statement
                        if not statements[current_statement]['title']:
                            statements[current_statement]['title'] = self.extract_table_title(page_text, current_statement)
                        if not statements[current_statement]['units']:
                            statements[current_statement]['units'] = self.extract_units(page_text)

                        # Process each raw table found on the page
                        for raw in raw_tables:
                            cleaned_df = self.clean_table_data(raw)
                            if cleaned_df is not None and not cleaned_df.empty:
                                # add page number if not already present
                                if page_num not in statements[current_statement]['pages']:
                                    statements[current_statement]['pages'].append(page_num)
                                statements[current_statement]['tables'].append(cleaned_df)
                    except Exception as e:
                        logger.warning(f"  Warning: error processing page {page_num} of {pdf_path.name}: {e}")
                        continue

        except Exception as e:
            logger.error(f"Error opening {pdf_path}: {e}")
            return None

        return statements

    # -------------------------
    # Merge / save helpers
    # -------------------------
    def merge_statement_tables(self, tables: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Merge multiple tables (from multiple pages) for the same statement into one DataFrame."""
        if not tables:
            return None
        if len(tables) == 1:
            return tables[0]

        try:
            merged = pd.concat(tables, ignore_index=True)
            # Remove duplicate rows resulting from page header repeats (same item text)
            merged = merged.drop_duplicates(subset=["item"], keep="first")
            merged = merged.reset_index(drop=True)
            return merged
        except Exception as e:
            logger.warning(f"Could not merge tables: {e}")
            return tables[0] if tables else None

    def save_statement_as_csv(self, statement_data: Dict, output_path: Path) -> bool:
        """Save extracted statement as CSV file"""
        if not statement_data or not statement_data.get('tables'):
            return False
    
        merged_df = self.merge_statement_tables(statement_data['tables'])
        if merged_df is None or merged_df.empty:
            return False
    
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save as CSV
            merged_df.to_csv(output_path, index=False, encoding='utf-8')
            
            # Save metadata as separate JSON
            metadata_path = output_path.with_suffix('.meta.json')
            metadata = {
                'title': statement_data.get('title'),
                'units': statement_data.get('units'),
                'pages': statement_data.get('pages'),
                'extracted_at': datetime.now().isoformat(),
                'rows': len(merged_df),
                'columns': list(merged_df.columns)
            }
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(f"  ✓ Saved {output_path.name} ({len(merged_df)} rows)")
            return True
        except Exception as e:
            logger.error(f"  ✗ Failed saving {output_path}: {e}")
            return False

    # -------------------------
    # PDF processing entrypoint
    # -------------------------
    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF and extract statements"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem

        output_files = {
            'balance_sheet': ticker_dir / f"{base_name}-balance-sheet.csv",
            'income_statement': ticker_dir / f"{base_name}-income-statement.csv",
            'cash_flow': ticker_dir / f"{base_name}-cash-flow.csv",
            'equity_changes': ticker_dir / f"{base_name}-equity-changes.csv"
        }

        if not force_reprocess and all(f.exists() for f in output_files.values()):
            logger.info(f"⊘ Already processed: {pdf_path.name}")
            return {'skipped': True, 'reason': 'already_processed'}

        logger.info(f"\n→ Processing: {pdf_path.name}")

        statements = self.extract_statement_from_pdf(pdf_path)
        if not statements:
            return {'skipped': True, 'reason': 'extraction_failed'}

        results = {}
        for statement_type, statement_data in statements.items():
            output_path = output_files[statement_type]
            success = self.save_statement_as_csv(statement_data, output_path)
            results[statement_type] = success

        return results

    # -------------------------
    # File discovery / batching
    # -------------------------
    def get_all_pdfs(self) -> List[Path]:
        pdfs: List[Path] = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name != '.git':
                ticker_pdfs = sorted(ticker_dir.glob("*.pdf"))
                pdfs.extend(ticker_pdfs)
        return pdfs

    def get_unprocessed_pdfs(self) -> List[Path]:
        all_pdfs = self.get_all_pdfs()
        unprocessed = []
        for pdf_path in all_pdfs:
            base_name = pdf_path.stem
            ticker_dir = pdf_path.parent
            output_files = [
                ticker_dir / f"{base_name}-balance-sheet.csv",
                ticker_dir / f"{base_name}-income-statement.csv",
                ticker_dir / f"{base_name}-cash-flow.csv",
                ticker_dir / f"{base_name}-equity-changes.csv"
            ]
            if not all(f.exists() for f in output_files):
                unprocessed.append(pdf_path)
        return unprocessed

    def get_pdf_batch(self, batch_number: int, batch_size: int = 10,
                      force_reprocess: bool = False) -> List[Path]:
        if force_reprocess:
            all_pdfs = self.get_all_pdfs()
        else:
            all_pdfs = self.get_unprocessed_pdfs()
        if not all_pdfs:
            return []
        start_idx = (batch_number - 1) * batch_size
        end_idx = start_idx + batch_size
        batch_pdfs = all_pdfs[start_idx:end_idx]
        logger.info("\n" + "=" * 70)
        logger.info(f"BATCH MODE: Processing Batch {batch_number}")
        logger.info(f"PDFs {start_idx + 1}-{min(end_idx, len(all_pdfs))} of {len(all_pdfs)}")
        logger.info("=" * 70 + "\n")
        return batch_pdfs

    def process_batch(self, pdfs: List[Path], force_reprocess: bool = False) -> Dict:
        summary = {
            'total': len(pdfs),
            'successful': 0,
            'skipped': 0,
            'failed': 0,
            'statements_extracted': {
                'balance_sheet': 0,
                'income_statement': 0,
                'cash_flow': 0,
                'equity_changes': 0
            }
        }
        for i, pdf_path in enumerate(pdfs, 1):
            try:
                logger.info(f"\n[{i}/{len(pdfs)}]")
                result = self.process_pdf(pdf_path, force_reprocess)
                if isinstance(result, dict) and result.get('skipped'):
                    summary['skipped'] += 1
                else:
                    summary['successful'] += 1
                    for statement_type, success in result.items():
                        if success:
                            summary['statements_extracted'][statement_type] += 1
            except Exception as e:
                logger.error(f"✗ Failed: {pdf_path.name} - {e}")
                summary['failed'] += 1
        return summary

    # -------------------------
    # Runner
    # -------------------------
    def run(self, batch_size: int = 10, force_reprocess: bool = False,
            batch_number: Optional[int] = None):
        start_time = datetime.now()
        logger.info("\n" + "=" * 70)
        logger.info("FINANCIAL STATEMENTS EXTRACTOR (pdfplumber-only)")
        logger.info("=" * 70)
        logger.info(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        # Determine PDFs to process
        if batch_number:
            pdfs_batch = self.get_pdf_batch(batch_number, batch_size, force_reprocess)
            if not pdfs_batch:
                logger.info(f"No PDFs to process in batch {batch_number}!")
                return
        else:
            if force_reprocess:
                logger.info("Force reprocess mode: Processing ALL PDFs")
                pdfs_batch = self.get_all_pdfs()
            else:
                logger.info("Processing only unprocessed PDFs")
                pdfs_batch = self.get_unprocessed_pdfs()
            if not pdfs_batch:
                logger.info("No PDFs to process!")
                return

        logger.info(f"Found {len(pdfs_batch)} PDFs to process")
        summary = self.process_batch(pdfs_batch, force_reprocess)

        # Batch summary logging
        logger.info("\nBatch Summary:")
        logger.info(f"  Total: {summary['total']}")
        logger.info(f"  Successful: {summary['successful']}")
        logger.info(f"  Skipped: {summary['skipped']}")
        logger.info(f"  Failed: {summary['failed']}")
        logger.info("  Statements extracted:")
        for stmt_type, count in summary['statements_extracted'].items():
            logger.info(f"    {stmt_type}: {count}")

        total_summary = {
            'extraction_date': datetime.now().isoformat(),
            'duration_seconds': (datetime.now() - start_time).total_seconds(),
            'batch_number': batch_number if batch_number else 'all',
            'batch_size': batch_size,
            'force_reprocess': force_reprocess,
            'total_pdfs': summary['total'],
            'successful': summary['successful'],
            'skipped': summary['skipped'],
            'failed': summary['failed'],
            'statements_extracted': summary['statements_extracted']
        }

        # Save summary
        if batch_number:
            summary_path = self.base_dir / f'extraction_summary_batch_{batch_number}.json'
        else:
            summary_path = self.base_dir / 'extraction_summary.json'
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(total_summary, f, indent=2, ensure_ascii=False)

        end_time = datetime.now()
        duration = end_time - start_time
        logger.info("\n" + "=" * 70)
        logger.info("EXTRACTION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total PDFs: {total_summary['total_pdfs']}")
        logger.info(f"Successful: {total_summary['successful']}")
        logger.info(f"Skipped: {total_summary['skipped']}")
        logger.info(f"Failed: {total_summary['failed']}")
        logger.info("\nStatements Extracted:")
        for stmt_type, count in total_summary['statements_extracted'].items():
            logger.info(f"  {stmt_type}: {count}")
        logger.info(f"\nDuration: {duration}")
        logger.info(f"Summary saved: {summary_path}")
        logger.info("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Extract financial statements from PDFs (pdfplumber-only)')
    parser.add_argument('--batch', type=int, default=None, help='Batch number (1-based)')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of PDFs per batch')
    parser.add_argument('--force', action='store_true', help='Force reprocess all PDFs')
    args = parser.parse_args()

    extractor = FinancialStatementsExtractor(base_dir="reports")
    extractor.run(
        batch_size=args.batch_size,
        force_reprocess=args.force,
        batch_number=args.batch
    )


if __name__ == '__main__':
    main()
