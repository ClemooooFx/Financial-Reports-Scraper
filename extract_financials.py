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

    def extract_table_title(self, page_text: str, table_bbox) -> str:
        """Extract text that appears above the table as the title"""
        if not page_text:
            return "Untitled Table"
        
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        
        # Get table's top position
        table_top = table_bbox[1] if table_bbox else 0
        
        # Look for the last non-empty line before the table starts
        # This is usually the table title
        title_lines = []
        for line in lines[:10]:  # Check first 10 lines
            if line and len(line) > 5:  # Skip very short lines
                title_lines.append(line)
        
        # Return the last substantial line as title, or first if none found
        if title_lines:
            return title_lines[-1] if len(title_lines) > 1 else title_lines[0]
        
        return "Untitled Table"

    def clean_table_data(self, table: List[List[str]]) -> Optional[pd.DataFrame]:
        """Convert raw table to clean DataFrame"""
        if not table or len(table) < 2:
            return None

        df = pd.DataFrame(table)
        
        # Remove completely empty rows and columns
        df = df.replace('', None).replace(r'^\s*$', None, regex=True)
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        
        if df.empty:
            return None
        
        df = df.reset_index(drop=True)
        
        # Use first row as headers
        headers = df.iloc[0].fillna('Column').astype(str).str.strip()
        df.columns = headers
        df = df.iloc[1:].reset_index(drop=True)
        
        # Replace empty cells with empty string
        df = df.fillna('')
        
        return df

    def extract_all_tables_from_pdf(self, pdf_path: Path) -> List[Dict]:
        """Extract ALL tables from a PDF"""
        all_tables = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    try:
                        page_text = page.extract_text() or ""
                        
                        # Extract all tables on this page
                        tables = page.extract_tables()
                        
                        if not tables:
                            continue
                        
                        for table_idx, raw_table in enumerate(tables):
                            cleaned_df = self.clean_table_data(raw_table)
                            
                            if cleaned_df is not None and not cleaned_df.empty:
                                # Try to get title from text above table
                                title = self.extract_table_title(page_text, None)
                                
                                table_info = {
                                    'page': page_num,
                                    'table_number': table_idx + 1,
                                    'title': title,
                                    'dataframe': cleaned_df
                                }
                                
                                all_tables.append(table_info)
                                logger.info(f"  ✓ Page {page_num}, Table {table_idx + 1}: {len(cleaned_df)} rows × {len(cleaned_df.columns)} cols")
                    
                    except Exception as e:
                        logger.warning(f"  ⚠ Page {page_num} error: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"✗ Error opening {pdf_path}: {e}")
            return []
        
        return all_tables

    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF and save all tables as CSV files"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem
        
        # Check if already processed (look for any CSV files with this base name)
        existing_csvs = list(ticker_dir.glob(f"{base_name}-table-*.csv"))
        
        if not force_reprocess and existing_csvs:
            logger.info(f"⊘ Already processed: {pdf_path.name} ({len(existing_csvs)} tables)")
            return {'skipped': True, 'reason': 'already_processed'}
        
        logger.info(f"\n→ Processing: {pdf_path.name}")
        
        # Extract all tables
        tables = self.extract_all_tables_from_pdf(pdf_path)
        
        if not tables:
            logger.warning(f"  ⚠ No tables found in {pdf_path.name}")
            return {'skipped': True, 'reason': 'no_tables_found'}
        
        # Save each table as a separate CSV
        saved_count = 0
        for table_info in tables:
            # Clean title for filename (remove special characters)
            clean_title = re.sub(r'[^\w\s-]', '', table_info['title'])
            clean_title = re.sub(r'\s+', '-', clean_title.strip())
            clean_title = clean_title[:50]  # Limit length to 50 chars
            
            # Create filename: 2024-ar-00-Statement-of-Financial-Position-p45.csv
            csv_filename = f"{base_name}-{clean_title}-p{table_info['page']}.csv"
            csv_path = ticker_dir / csv_filename
            
            try:
                # Save CSV
                table_info['dataframe'].to_csv(csv_path, index=False, encoding='utf-8')
                
                # Save metadata
                metadata_path = csv_path.with_suffix('.meta.json')
                metadata = {
                    'source_pdf': pdf_path.name,
                    'page': table_info['page'],
                    'table_number': table_info['table_number'],
                    'title': table_info['title'],
                    'rows': len(table_info['dataframe']),
                    'columns': list(table_info['dataframe'].columns),
                    'extracted_at': datetime.now().isoformat()
                }
                
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                
                saved_count += 1
            
            except Exception as e:
                logger.error(f"  ✗ Failed to save table: {e}")
        
        logger.info(f"  ✓ Saved {saved_count}/{len(tables)} tables")
        return {'tables_extracted': saved_count}

    def get_all_pdfs(self) -> List[Path]:
        pdfs = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name not in ['.git', '__pycache__']:
                ticker_pdfs = sorted(ticker_dir.glob("*.pdf"))
                pdfs.extend(ticker_pdfs)
        return pdfs

    def get_unprocessed_pdfs(self) -> List[Path]:
        """Get PDFs that don't have any CSV tables extracted yet"""
        all_pdfs = self.get_all_pdfs()
        unprocessed = []
        
        for pdf_path in all_pdfs:
            base_name = pdf_path.stem
            ticker_dir = pdf_path.parent
            
            # Check if any tables exist for this PDF
            existing_tables = list(ticker_dir.glob(f"{base_name}-*-p*.csv"))
            
            if not existing_tables:
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
        logger.info(f"BATCH {batch_number}: PDFs {start_idx + 1}-{min(end_idx, len(all_pdfs))} of {len(all_pdfs)}")
        logger.info("=" * 70 + "\n")
        
        return batch_pdfs

    def process_batch(self, pdfs: List[Path], force_reprocess: bool = False) -> Dict:
        summary = {
            'total': len(pdfs),
            'successful': 0,
            'skipped': 0,
            'failed': 0,
            'total_tables_extracted': 0
        }
        
        for i, pdf_path in enumerate(pdfs, 1):
            try:
                logger.info(f"\n[{i}/{len(pdfs)}]")
                result = self.process_pdf(pdf_path, force_reprocess)
                
                if isinstance(result, dict) and result.get('skipped'):
                    summary['skipped'] += 1
                else:
                    summary['successful'] += 1
                    summary['total_tables_extracted'] += result.get('tables_extracted', 0)
            
            except Exception as e:
                logger.error(f"✗ Failed: {pdf_path.name} - {e}")
                summary['failed'] += 1
        
        return summary

    def run(self, batch_size: int = 10, force_reprocess: bool = False,
            batch_number: Optional[int] = None):
        start_time = datetime.now()
        
        print("\n" + "="*70)
        print("PDF TABLE EXTRACTOR - Extract ALL Tables")
        print("="*70)
        logger.info(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get PDFs to process
        if batch_number:
            pdfs_batch = self.get_pdf_batch(batch_number, batch_size, force_reprocess)
            if not pdfs_batch:
                logger.info(f"No PDFs in batch {batch_number}")
                return
        else:
            if force_reprocess:
                logger.info("Mode: Reprocess ALL PDFs")
                pdfs_batch = self.get_all_pdfs()
            else:
                logger.info("Mode: Process unprocessed PDFs only")
                pdfs_batch = self.get_unprocessed_pdfs()
            
            if not pdfs_batch:
                logger.info("✓ No PDFs to process!")
                return
        
        logger.info(f"Found: {len(pdfs_batch)} PDFs to process\n")
        
        # Process batch
        summary = self.process_batch(pdfs_batch, force_reprocess)
        
        # Save summary
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
            'total_tables_extracted': summary['total_tables_extracted']
        }
        
        if batch_number:
            summary_path = self.base_dir / f'extraction_summary_batch_{batch_number}.json'
        else:
            summary_path = self.base_dir / 'extraction_summary.json'
        
        with open(summary_path, 'w') as f:
            json.dump(total_summary, f, indent=2)
        
        # Final summary
        duration = datetime.now() - start_time
        
        print("\n" + "="*70)
        print("EXTRACTION COMPLETE")
        print("="*70)
        print(f"Total PDFs:    {total_summary['total_pdfs']}")
        print(f"Successful:    {total_summary['successful']}")
        print(f"Skipped:       {total_summary['skipped']}")
        print(f"Failed:        {total_summary['failed']}")
        print(f"Tables:        {total_summary['total_tables_extracted']}")
        print(f"Duration:      {duration}")
        print(f"Summary:       {summary_path}")
        print("="*70 + "\n")

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
