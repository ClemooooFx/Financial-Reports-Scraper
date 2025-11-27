"""
Financial Statements Extractor
Extracts Balance Sheet, Income Statement, Cash Flow, and Equity Changes from PDF reports
"""

import pdfplumber
import pandas as pd
import json
from pathlib import Path
import re
from datetime import datetime
import argparse
from typing import Dict, List, Tuple, Optional
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinancialStatementsExtractor:
    def __init__(self, base_dir="reports"):
        self.base_dir = Path(base_dir)
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
        
    def identify_statement_type(self, text: str) -> Optional[str]:
        """Identify which financial statement this page contains"""
        text_lower = text.lower()
        
        for statement_type, keywords in self.statement_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return statement_type
        return None
    
    def extract_units(self, text: str) -> Optional[str]:
        """Extract the unit of measurement from text"""
        patterns = [
            r'in\s+(\w+)\s+(?:kenya\s+)?shillings?',
            r'figures?\s+in\s+(\w+)',
            r'amounts?\s+in\s+(\w+)',
            r'\((?:kshs?\.?\s+)?[\'"]?(\w+)[\'"]?\)',
            r'shs\.?\s+[\'"]?(\w+)[\'"]?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                unit = match.group(1).lower()
                # Normalize unit names
                if 'thousand' in unit:
                    return 'thousands'
                elif 'million' in unit:
                    return 'millions'
                elif 'billion' in unit:
                    return 'billions'
                return unit
        return None
    
    def extract_table_title(self, text: str, statement_type: str) -> str:
        """Extract the exact table title from the page"""
        lines = text.split('\n')
        keywords = self.statement_keywords[statement_type]
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            for keyword in keywords:
                if keyword in line_lower:
                    # Return the original line (with proper casing)
                    title = line.strip()
                    # Sometimes title spans multiple lines
                    if i + 1 < len(lines) and len(lines[i + 1].strip()) < 50:
                        title += ' ' + lines[i + 1].strip()
                    return title
        
        # Default titles
        defaults = {
            'balance_sheet': 'Statement of Financial Position',
            'income_statement': 'Statement of Profit or Loss',
            'cash_flow': 'Statement of Cash Flows',
            'equity_changes': 'Statement of Changes in Equity'
        }
        return defaults.get(statement_type, 'Financial Statement')
    
    def clean_table_data(self, table: List[List]) -> pd.DataFrame:
        """Clean and structure table data"""
        if not table:
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(table)
        
        # Remove completely empty rows and columns
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        
        if df.empty:
            return None
        
        # Try to identify header row (usually first non-empty row)
        # Reset index after dropping rows
        df = df.reset_index(drop=True)
        
        # Use first row as headers if it looks like headers
        if len(df) > 0:
            headers = df.iloc[0].fillna('')
            # Check if first row looks like headers (contains text, not just numbers)
            if any(isinstance(h, str) and not h.replace(',', '').replace('.', '').isdigit() 
                   for h in headers if h):
                df.columns = headers
                df = df.iloc[1:]
        
        return df
    
    def extract_statement_from_pdf(self, pdf_path: Path) -> Dict:
        """Extract all financial statements from a PDF"""
        statements = {
            'balance_sheet': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'income_statement': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'cash_flow': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'equity_changes': {'tables': [], 'title': None, 'units': None, 'pages': []}
        }
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if not text:
                        continue
                    
                    statement_type = self.identify_statement_type(text)
                    
                    if statement_type:
                        # Extract tables from this page
                        tables = page.extract_tables()
                        
                        if tables:
                            # Get title and units if not already set
                            if not statements[statement_type]['title']:
                                statements[statement_type]['title'] = self.extract_table_title(text, statement_type)
                            
                            if not statements[statement_type]['units']:
                                statements[statement_type]['units'] = self.extract_units(text)
                            
                            # Process each table
                            for table in tables:
                                cleaned_df = self.clean_table_data(table)
                                if cleaned_df is not None and not cleaned_df.empty:
                                    statements[statement_type]['tables'].append(cleaned_df)
                                    statements[statement_type]['pages'].append(page_num)
        
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
            return None
        
        return statements
    
    def merge_statement_tables(self, tables: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Merge multiple tables for the same statement (e.g., split across pages)"""
        if not tables:
            return None
        
        if len(tables) == 1:
            return tables[0]
        
        # Try to concatenate tables vertically
        try:
            merged = pd.concat(tables, ignore_index=True)
            return merged
        except Exception as e:
            logger.warning(f"Could not merge tables: {e}")
            # Return the largest table if merge fails
            return max(tables, key=len)
    
    def save_statement_as_json(self, statement_data: Dict, output_path: Path):
        """Save extracted statement as JSON"""
        if not statement_data['tables']:
            return False
        
        merged_df = self.merge_statement_tables(statement_data['tables'])
        
        if merged_df is None or merged_df.empty:
            return False
        
        # Prepare output data
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
        
        logger.info(f"Saved {output_path.name}")
        return True
    
    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF and extract financial statements"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem  # e.g., "2024-ar-00"
        
        # Check if already processed
        output_files = {
            'balance_sheet': ticker_dir / f"{base_name}-balance-sheet.json",
            'income_statement': ticker_dir / f"{base_name}-income-statement.json",
            'cash_flow': ticker_dir / f"{base_name}-cash-flow.json",
            'equity_changes': ticker_dir / f"{base_name}-equity-changes.json"
        }
        
        if not force_reprocess and all(f.exists() for f in output_files.values()):
            logger.info(f"Already processed: {pdf_path.name} (use --force to reprocess)")
            return {'skipped': True, 'reason': 'already_processed'}
        
        logger.info(f"Processing: {pdf_path.name}")
        
        # Extract statements
        statements = self.extract_statement_from_pdf(pdf_path)
        
        if not statements:
            return {'skipped': True, 'reason': 'extraction_failed'}
        
        # Save each statement
        # Save each statement
        results = {}
        for statement_type, statement_data in statements.items():
            output_path = output_files[statement_type]
            success = self.save_statement_as_json(statement_data, output_path)
            results[statement_type] = success
        
        return results
    
    def get_all_pdfs(self) -> List[Path]:
        """Get all PDF files in the reports directory"""
        pdfs = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name != '.git':
                # Get all PDFs in this ticker directory
                ticker_pdfs = sorted(ticker_dir.glob("*.pdf"))
                pdfs.extend(ticker_pdfs)
        return pdfs
    
    def get_unprocessed_pdfs(self) -> List[Path]:
        """Get PDFs that haven't been processed yet"""
        all_pdfs = self.get_all_pdfs()
        unprocessed = []
        
        for pdf_path in all_pdfs:
            base_name = pdf_path.stem
            ticker_dir = pdf_path.parent
            
            # Check if any of the 4 output files are missing
            output_files = [
                ticker_dir / f"{base_name}-balance-sheet.json",
                ticker_dir / f"{base_name}-income-statement.json",
                ticker_dir / f"{base_name}-cash-flow.json",
                ticker_dir / f"{base_name}-equity-changes.json"
            ]
            
            if not all(f.exists() for f in output_files):
                unprocessed.append(pdf_path)
        
        return unprocessed


    def get_pdf_batch(self, batch_number: int, batch_size: int = 10, 
                      force_reprocess: bool = False) -> List[Path]:
        """Get a specific batch of PDFs"""
        # Get all PDFs based on force_reprocess flag
        if force_reprocess:
            all_pdfs = self.get_all_pdfs()
        else:
            all_pdfs = self.get_unprocessed_pdfs()
        
        if not all_pdfs:
            return []
        
        # Calculate batch indices
        start_idx = (batch_number - 1) * batch_size
        end_idx = start_idx + batch_size
        
        # Get batch
        batch_pdfs = all_pdfs[start_idx:end_idx]
        
        logger.info(f"\n{'='*70}")
        logger.info(f"BATCH MODE: Processing Batch {batch_number}")
        logger.info(f"PDFs {start_idx + 1}-{min(end_idx, len(all_pdfs))} of {len(all_pdfs)}")
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
                'balance_sheet': 0,
                'income_statement': 0,
                'cash_flow': 0,
                'equity_changes': 0
            }
        }
        
        for pdf_path in pdfs:
            try:
                result = self.process_pdf(pdf_path, force_reprocess)
                
                if isinstance(result, dict) and result.get('skipped'):
                    summary['skipped'] += 1
                else:
                    summary['successful'] += 1
                    # Count extracted statements
                    for statement_type, success in result.items():
                        if success:
                            summary['statements_extracted'][statement_type] += 1
            
            except Exception as e:
                logger.error(f"Failed to process {pdf_path}: {e}")
                summary['failed'] += 1
        
        return summary
    
    def run(self, batch_size: int = 10, force_reprocess: bool = False, 
            batch_number: Optional[int] = None):
        """Main execution"""
        start_time = datetime.now()
        
        logger.info("\n" + "="*70)
        logger.info("FINANCIAL STATEMENTS EXTRACTOR")
        logger.info("="*70)
        logger.info(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get PDFs to process - use batch method if batch_number provided
        if batch_number:
            pdfs_batch = self.get_pdf_batch(batch_number, batch_size, force_reprocess)
            if not pdfs_batch:
                logger.info(f"No PDFs to process in batch {batch_number}!")
                return
        else:
            # Process all PDFs
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
        
        # Process the batch (no chunking needed - batch is already the right size)
        summary = self.process_batch(pdfs_batch, force_reprocess)
        
        logger.info(f"\nBatch Summary:")
        logger.info(f"  Total: {summary['total']}")
        logger.info(f"  Successful: {summary['successful']}")
        logger.info(f"  Skipped: {summary['skipped']}")
        logger.info(f"  Failed: {summary['failed']}")
        logger.info(f"  Statements extracted:")
        for stmt_type, count in summary['statements_extracted'].items():
            logger.info(f"    {stmt_type}: {count}")
        
        # Prepare final summary
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
        
        with open(summary_path, 'w') as f:
            json.dump(total_summary, f, indent=2)
        
        # Final summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("\n" + "="*70)
        logger.info("EXTRACTION COMPLETE")
        logger.info("="*70)
        logger.info(f"Total PDFs: {total_summary['total_pdfs']}")
        logger.info(f"Successful: {total_summary['successful']}")
        logger.info(f"Skipped: {total_summary['skipped']}")
        logger.info(f"Failed: {total_summary['failed']}")
        logger.info(f"\nStatements Extracted:")
        for stmt_type, count in total_summary['statements_extracted'].items():
            logger.info(f"  {stmt_type}: {count}")
        logger.info(f"\nDuration: {duration}")
        logger.info(f"Summary saved: {summary_path}")
        logger.info("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Extract financial statements from PDFs')
    parser.add_argument('--batch', type=int, default=None,
                       help='Batch number to process')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='Number of PDFs per batch')
    parser.add_argument('--force', action='store_true',
                       help='Force reprocess all PDFs (including already processed)')
    
    args = parser.parse_args()
    
    extractor = FinancialStatementsExtractor(base_dir="reports")
    extractor.run(
        batch_size=args.batch_size,
        force_reprocess=args.force,
        batch_number=args.batch
    )


if __name__ == '__main__':
    main()
