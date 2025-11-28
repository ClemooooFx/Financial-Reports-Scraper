"""
Financial Statements Extractor using Camelot with OCR Support
Extracts Consolidated Financial Statements from Annual Report PDFs
Uses Camelot for accurate table detection with both text and numbers
Supports OCR for image-based PDFs using Tesseract
"""

import camelot
import pandas as pd
import json
from pathlib import Path
import re
from datetime import datetime
import argparse
from typing import Dict, List, Optional
import logging
import subprocess
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinancialStatementsExtractor:
    def __init__(self, base_dir="reports", use_ocr=True):
        self.base_dir = Path(base_dir)
        self.use_ocr = use_ocr
        
        # Check if Tesseract is available
        if use_ocr:
            try:
                result = subprocess.run(['tesseract', '--version'], 
                                      capture_output=True, text=True)
                logger.info(f"  Tesseract OCR available: {result.stdout.split()[1]}")
            except FileNotFoundError:
                logger.warning("  Tesseract not found. OCR will be disabled.")
                logger.warning("  Install: sudo apt-get install tesseract-ocr (Ubuntu)")
                self.use_ocr = False
        
        # Target only consolidated statements
        self.statement_keywords = {
            'consolidated_financial_position': [
                'consolidated statement of financial position',
                'consolidated statement of financial position',
            ],
            'consolidated_income': [
                'consolidated income statement',
                'consolidated statement of profit or loss',
                'consolidated statement of comprehensive income',
            ],
            'consolidated_equity': [
                'consolidated statement of changes in equity',
            ],
            'consolidated_cashflow': [
                'consolidated statement of cash flows',
                'consolidated cash flow statement',
            ]
        }
        
        # Financial data indicators (must have actual numbers)
        self.data_indicators = {
            'consolidated_financial_position': ['assets', 'liabilities', 'equity', 'total'],
            'consolidated_income': ['income', 'expenses', 'profit', 'tax'],
            'consolidated_equity': ['balance', 'share capital', 'reserves'],
            'consolidated_cashflow': ['cash flow', 'operating', 'investing', 'financing']
        }
        
    def is_image_based_pdf(self, pdf_path: Path) -> bool:
        """Check if PDF is image-based (scanned)"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            # Check first 3 pages
            for page_num in range(min(3, len(doc))):
                page = doc[page_num]
                text = page.get_text().strip()
                # If page has very little text, likely image-based
                if len(text) < 100:
                    doc.close()
                    return True
            doc.close()
            return False
        except:
            return False
    
    def extract_tables_with_ocr(self, pdf_path: Path) -> List:
        """Extract tables using OCR for image-based PDFs"""
        try:
            # First convert PDF to images, then use OCR
            logger.info(f"  Using OCR mode for image-based PDF...")
            
            # Use pdf-backend for OCR
            tables = camelot.read_pdf(
                str(pdf_path),
                pages='all',
                flavor='lattice',
                backend='ghostscript',
                line_scale=40,
                copy_text=['v'],
                strip_text=' \n'
            )
            
            if len(tables) == 0:
                # Try stream mode with OCR
                tables = camelot.read_pdf(
                    str(pdf_path),
                    pages='all',
                    flavor='stream',
                    backend='ghostscript',
                    edge_tol=50,
                    strip_text=' \n'
                )
            
            return tables
        except Exception as e:
            logger.error(f"  OCR extraction failed: {e}")
            return []
        """Extract text from a specific page using PyMuPDF"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]
            text = page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.warning(f"  Could not extract text from page {page_num}: {e}")
            return ""
            
    def extract_page_text(self, pdf_path: Path, page_num: int) -> str:
        """Extract text from a specific page using PyMuPDF"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            page = doc[page_num - 1]
            text = page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.warning(f"  Could not extract text from page {page_num}: {e}")
            return ""
    
    def identify_statement_type(self, text: str) -> Optional[str]:
        """Identify which consolidated financial statement this text contains"""
        text_lower = text.lower()
        
        # Must contain "consolidated" keyword
        if 'consolidated' not in text_lower:
            return None
        
        # Check for statement type
        for statement_type, keywords in self.statement_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return statement_type
        
        return None
    
    def has_financial_data(self, df: pd.DataFrame, statement_type: str) -> bool:
        """Check if DataFrame contains actual financial data with numbers"""
        if df.empty or len(df) < 5:
            return False
        
        text_content = ' '.join(df.astype(str).values.flatten()).lower()
        
        # Check for statement-specific indicators
        indicators = self.data_indicators.get(statement_type, [])
        indicator_count = sum(1 for indicator in indicators if indicator in text_content)
        
        if indicator_count < 2:
            return False
        
        # Must have numeric data (financial numbers like 1,234,567 or 12,345)
        numeric_pattern = r'\d{1,3}(?:,\d{3})+|\d{4,}'
        large_number_count = 0
        for col in df.columns:
            col_str = ' '.join(df[col].astype(str))
            matches = re.findall(numeric_pattern, col_str)
            large_number_count += len(matches)
        
        # Should have at least 15 financial numbers
        return large_number_count >= 15
    
    def has_year_columns(self, df: pd.DataFrame) -> bool:
        """Check if table has year columns (2018-2025)"""
        year_pattern = r'20[1-2][0-9]'
        
        for idx in range(min(5, len(df))):
            row_text = ' '.join(df.iloc[idx].astype(str))
            if re.search(year_pattern, row_text):
                return True
        
        return False
    
    def extract_units(self, text: str) -> Optional[str]:
        """Extract the unit of measurement from text"""
        patterns = [
            r"in\s+(\w+)\s+(?:kenya\s+)?shillings?",
            r"kshs?\s*['\"]?(\w+)['\"]?",
            r"figures?\s+in\s+(\w+)",
            r"amounts?\s+in\s+(\w+)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                unit = match.group(1).lower()
                if 'thousand' in unit:
                    return 'thousands'
                elif 'million' in unit:
                    return 'millions'
                elif 'billion' in unit:
                    return 'billions'
                return unit
        return None
    
    def extract_table_title(self, page_text: str, statement_type: str) -> str:
        """Extract the exact table title"""
        lines = [line.strip() for line in page_text.split('\n') if line.strip()]
        keywords = self.statement_keywords[statement_type]
        
        for i, line in enumerate(lines[:25]):
            line_lower = line.lower()
            for keyword in keywords:
                if keyword in line_lower:
                    title = line
                    # Check for subtitle on next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if len(next_line) < 100 and 'as at' in next_line.lower() or 'for the year' in next_line.lower():
                            title += ' ' + next_line
                    return title
        
        # Default titles
        defaults = {
            'consolidated_financial_position': 'Consolidated Statement of Financial Position',
            'consolidated_income': 'Consolidated Income Statement',
            'consolidated_cashflow': 'Consolidated Statement of Cash Flows',
            'consolidated_equity': 'Consolidated Statement of Changes in Equity'
        }
        return defaults.get(statement_type, 'Financial Statement')
    
    def clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean the extracted DataFrame"""
        # Remove completely empty rows and columns
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        df = df.reset_index(drop=True)
        
        if df.empty:
            return df
        
        # Find header row (contains 'Note', year numbers, or common headers)
        header_row_idx = None
        for idx in range(min(8, len(df))):
            row_text = ' '.join(df.iloc[idx].astype(str)).lower()
            if any(term in row_text for term in ['note', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025', 'kshs']):
                header_row_idx = idx
                break
        
        # Use found header or first row
        if header_row_idx is not None and header_row_idx > 0:
            df = df.iloc[header_row_idx:].reset_index(drop=True)
        
        # Set first row as column names
        if len(df) > 0:
            new_columns = []
            for i, col in enumerate(df.iloc[0]):
                col_str = str(col).strip() if pd.notna(col) else f'Column_{i}'
                # Clean column name
                col_str = col_str.replace('\n', ' ').strip()
                new_columns.append(col_str)
            
            df.columns = new_columns
            df = df.iloc[1:].reset_index(drop=True)
        
        # Fill NaN with empty strings
        df = df.fillna('')
        
        # Remove rows that are all empty or dashes
        df = df[~df.apply(lambda row: all(str(val).strip() in ['', '-', '—', 'nan'] for val in row), axis=1)]
        
        return df.reset_index(drop=True)
    
    def extract_statement_from_pdf(self, pdf_path: Path) -> Dict:
        """Extract consolidated financial statements from PDF"""
        statements = {
            'consolidated_financial_position': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'consolidated_income': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'consolidated_cashflow': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'consolidated_equity': {'tables': [], 'title': None, 'units': None, 'pages': []}
        }
        
        try:
            # Check if PDF is image-based
            is_image_pdf = self.use_ocr and self.is_image_based_pdf(pdf_path)
            
            if is_image_pdf:
                logger.info(f"  Detected image-based PDF, using OCR...")
                tables = self.extract_tables_with_ocr(pdf_path)
            else:
                logger.info(f"  Extracting tables with Camelot...")
                
                # Try lattice mode first (better for bordered tables)
                try:
                    tables = camelot.read_pdf(
                        str(pdf_path), 
                        pages='all', 
                        flavor='lattice',
                        line_scale=40,
                        strip_text=' \n'
                    )
                    logger.info(f"  Found {len(tables)} tables using lattice mode")
                except Exception as e:
                    logger.warning(f"  Lattice mode failed, trying stream mode")
                    try:
                        tables = camelot.read_pdf(
                            str(pdf_path), 
                            pages='all', 
                            flavor='stream',
                            edge_tol=50,
                            strip_text=' \n'
                        )
                        logger.info(f"  Found {len(tables)} tables using stream mode")
                    except Exception as e2:
                        # Last resort: use OCR backend
                        if self.use_ocr:
                            logger.warning(f"  Stream mode failed, using OCR backend")
                            tables = self.extract_tables_with_ocr(pdf_path)
                            logger.info(f"  Found {len(tables)} tables using OCR")
                        else:
                            logger.error(f"  All extraction methods failed")
                            return None
            
            # Process each table
            for idx, table in enumerate(tables):
                try:
                    page_num = table.page
                    df = table.df
                    
                    # Get page text for context
                    page_text = self.extract_page_text(pdf_path, page_num)
                    
                    # Identify statement type
                    statement_type = self.identify_statement_type(page_text)
                    
                    if statement_type:
                        # Validate it's a financial table with data
                        if self.has_financial_data(df, statement_type) and self.has_year_columns(df):
                            logger.info(f"  ✓ Found {statement_type} on page {page_num}")
                            
                            # Extract metadata
                            if not statements[statement_type]['title']:
                                statements[statement_type]['title'] = self.extract_table_title(page_text, statement_type)
                            
                            if not statements[statement_type]['units']:
                                statements[statement_type]['units'] = self.extract_units(page_text)
                            
                            # Clean and store DataFrame
                            cleaned_df = self.clean_dataframe(df)
                            if not cleaned_df.empty:
                                statements[statement_type]['tables'].append(cleaned_df)
                                if page_num not in statements[statement_type]['pages']:
                                    statements[statement_type]['pages'].append(page_num)
                
                except Exception as e:
                    logger.warning(f"  Error processing table {idx+1}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"  Error processing PDF: {e}")
            return None
        
        return statements
    
    def merge_statement_tables(self, tables: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Merge multiple tables for the same statement"""
        if not tables:
            return None
        
        if len(tables) == 1:
            return tables[0]
        
        try:
            # Try to concatenate vertically
            merged = pd.concat(tables, ignore_index=True)
            return merged
        except Exception as e:
            logger.warning(f"  Could not merge tables: {e}")
            return max(tables, key=len)
    
    def save_statement_as_json(self, statement_data: Dict, output_path: Path):
        """Save extracted statement as JSON"""
        if not statement_data['tables']:
            return False
        
        merged_df = self.merge_statement_tables(statement_data['tables'])
        
        if merged_df is None or merged_df.empty:
            return False
        
        # Prepare output
        output = {
            'title': statement_data['title'],
            'units': statement_data['units'],
            'pages': statement_data['pages'],
            'extracted_at': datetime.now().isoformat(),
            'data': merged_df.to_dict(orient='records')
        }
        
        # Save to JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        logger.info(f"  ✓ Saved {output_path.name} ({len(merged_df)} rows)")
        return True
    
    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem
        
        # Output files
        output_files = {
            'consolidated_financial_position': ticker_dir / f"{base_name}-consolidated-financial-position.json",
            'consolidated_income': ticker_dir / f"{base_name}-consolidated-income.json",
            'consolidated_cashflow': ticker_dir / f"{base_name}-consolidated-cashflow.json",
            'consolidated_equity': ticker_dir / f"{base_name}-consolidated-equity.json"
        }
        
        if not force_reprocess and all(f.exists() for f in output_files.values()):
            logger.info(f"⊘ Already processed: {pdf_path.name}")
            return {'skipped': True, 'reason': 'already_processed'}
        
        logger.info(f"\n→ Processing: {pdf_path.name}")
        
        # Extract statements
        statements = self.extract_statement_from_pdf(pdf_path)
        
        if not statements:
            return {'skipped': True, 'reason': 'extraction_failed'}
        
        # Save each statement
        results = {}
        for statement_type, statement_data in statements.items():
            output_path = output_files[statement_type]
            success = self.save_statement_as_json(statement_data, output_path)
            results[statement_type] = success
        
        return results
    
    def get_all_pdfs(self) -> List[Path]:
        """Get all PDF files"""
        pdfs = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name != '.git':
                ticker_pdfs = sorted(ticker_dir.glob("*.pdf"))
                pdfs.extend(ticker_pdfs)
        return pdfs
    
    def get_unprocessed_pdfs(self) -> List[Path]:
        """Get PDFs that haven't been processed"""
        all_pdfs = self.get_all_pdfs()
        unprocessed = []
        
        for pdf_path in all_pdfs:
            base_name = pdf_path.stem
            ticker_dir = pdf_path.parent
            
            output_files = [
                ticker_dir / f"{base_name}-consolidated-financial-position.json",
                ticker_dir / f"{base_name}-consolidated-income.json",
                ticker_dir / f"{base_name}-consolidated-cashflow.json",
                ticker_dir / f"{base_name}-consolidated-equity.json"
            ]
            
            if not all(f.exists() for f in output_files):
                unprocessed.append(pdf_path)
        
        return unprocessed
    
    def get_pdf_batch(self, batch_number: int, batch_size: int = 10, 
                      force_reprocess: bool = False) -> List[Path]:
        """Get a specific batch of PDFs"""
        if force_reprocess:
            all_pdfs = self.get_all_pdfs()
        else:
            all_pdfs = self.get_unprocessed_pdfs()
        
        if not all_pdfs:
            return []
        
        start_idx = (batch_number - 1) * batch_size
        end_idx = start_idx + batch_size
        batch_pdfs = all_pdfs[start_idx:end_idx]
        
        logger.info(f"\n{'='*70}")
        logger.info(f"BATCH {batch_number}: PDFs {start_idx + 1}-{min(end_idx, len(all_pdfs))} of {len(all_pdfs)}")
        logger.info(f"{'='*70}\n")
        
        return batch_pdfs
    
    def process_batch(self, pdfs: List[Path], force_reprocess: bool = False) -> Dict:
        """Process a batch of PDFs"""
        summary = {
            'total': len(pdfs),
            'successful': 0,
            'skipped': 0,
            'failed': 0,
            'statements_extracted': {
                'consolidated_financial_position': 0,
                'consolidated_income': 0,
                'consolidated_cashflow': 0,
                'consolidated_equity': 0
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
    
    def run(self, batch_size: int = 10, force_reprocess: bool = False, 
            batch_number: Optional[int] = None):
        """Main execution"""
        start_time = datetime.now()
        
        logger.info("\n" + "="*70)
        logger.info("CONSOLIDATED FINANCIAL STATEMENTS EXTRACTOR")
        logger.info("="*70)
        
        # Get PDFs to process
        if batch_number:
            pdfs_batch = self.get_pdf_batch(batch_number, batch_size, force_reprocess)
            if not pdfs_batch:
                logger.info(f"No PDFs in batch {batch_number}!")
                return
        else:
            if force_reprocess:
                pdfs_batch = self.get_all_pdfs()
            else:
                pdfs_batch = self.get_unprocessed_pdfs()
            
            if not pdfs_batch:
                logger.info("No PDFs to process!")
                return
        
        logger.info(f"Found {len(pdfs_batch)} PDFs to process")
        
        # Process batch
        summary = self.process_batch(pdfs_batch, force_reprocess)
        
        # Summary
        total_summary = {
            'extraction_date': datetime.now().isoformat(),
            'duration_seconds': (datetime.now() - start_time).total_seconds(),
            'batch_number': batch_number if batch_number else 'all',
            'total_pdfs': summary['total'],
            'successful': summary['successful'],
            'skipped': summary['skipped'],
            'failed': summary['failed'],
            'statements_extracted': summary['statements_extracted']
        }
        
        # Save summary
        summary_path = self.base_dir / f'extraction_summary_batch_{batch_number}.json' if batch_number else self.base_dir / 'extraction_summary.json'
        with open(summary_path, 'w') as f:
            json.dump(total_summary, f, indent=2)
        
        # Final output
        duration = datetime.now() - start_time
        logger.info("\n" + "="*70)
        logger.info("EXTRACTION COMPLETE")
        logger.info("="*70)
        logger.info(f"Total: {summary['total']} | Success: {summary['successful']} | Skipped: {summary['skipped']} | Failed: {summary['failed']}")
        logger.info(f"\nStatements Extracted:")
        for stmt_type, count in summary['statements_extracted'].items():
            logger.info(f"  {stmt_type}: {count}")
        logger.info(f"\nDuration: {duration}")
        logger.info("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Extract consolidated financial statements from PDFs')
    parser.add_argument('--batch', type=int, default=None, help='Batch number')
    parser.add_argument('--batch-size', type=int, default=10, help='PDFs per batch')
    parser.add_argument('--force', action='store_true', help='Force reprocess all PDFs')
    parser.add_argument('--no-ocr', action='store_true', help='Disable OCR for image-based PDFs')
    
    args = parser.parse_args()
    
    extractor = FinancialStatementsExtractor(
        base_dir="reports",
        use_ocr=not args.no_ocr
    )
    extractor.run(
        batch_size=args.batch_size,
        force_reprocess=args.force,
        batch_number=args.batch
    )


if __name__ == '__main__':
    main()
