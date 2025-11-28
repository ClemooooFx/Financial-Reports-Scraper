"""
Financial Statements Extractor using Camelot
Extracts Balance Sheet, Income Statement, Cash Flow, and Equity Changes from PDF reports
Uses Camelot for accurate table detection and extraction with context
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
                'consolidated statement of profit',
                'consolidated statement of comprehensive income'
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
        
        # Financial statement indicators (items typically found in statements)
        self.financial_indicators = {
            'balance_sheet': ['assets', 'liabilities', 'equity', 'non-current', 'current'],
            'income_statement': ['revenue', 'income', 'expenses', 'profit', 'loss', 'tax'],
            'cash_flow': ['cash flow', 'operating activities', 'investing activities', 'financing activities'],
            'equity_changes': ['share capital', 'retained earnings', 'reserves', 'balance at']
        }
        
    def identify_statement_type(self, text: str) -> Optional[str]:
        """Identify which financial statement this text contains"""
        text_lower = text.lower()
        
        # First, check for explicit statement titles
        for statement_type, keywords in self.statement_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    # Verify it's actually a financial statement by checking for indicators
                    indicators = self.financial_indicators.get(statement_type, [])
                    if any(indicator in text_lower for indicator in indicators):
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
            r'all\s+amounts?\s+are\s+in\s+(\w+)',
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
        """Extract the exact table title from the text"""
        lines = text.split('\n')
        keywords = self.statement_keywords[statement_type]
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            for keyword in keywords:
                if keyword in line_lower:
                    # Return the original line (with proper casing)
                    title = line.strip()
                    # Sometimes title spans multiple lines
                    if i + 1 < len(lines) and len(lines[i + 1].strip()) < 80:
                        next_line = lines[i + 1].strip()
                        # Only add if it looks like a continuation (not a column header)
                        if next_line and not any(word in next_line.lower() for word in ['note', '2018', '2019', '2020', '2021', '2022', '2023', '2024']):
                            title += ' ' + next_line
                    return title
        
        # Default titles
        defaults = {
            'balance_sheet': 'Statement of Financial Position',
            'income_statement': 'Statement of Comprehensive Income',
            'cash_flow': 'Statement of Cash Flows',
            'equity_changes': 'Statement of Changes in Equity'
        }
        return defaults.get(statement_type, 'Financial Statement')
    
    def is_financial_table(self, df: pd.DataFrame, statement_type: str) -> bool:
        """Check if a DataFrame contains actual financial data"""
        if df.empty or len(df) < 3:
            return False
        
        # Convert to string and check for financial indicators
        text_content = ' '.join(df.astype(str).values.flatten()).lower()
        
        # Check for statement-specific indicators
        indicators = self.financial_indicators.get(statement_type, [])
        indicator_count = sum(1 for indicator in indicators if indicator in text_content)
        
        # Check for numeric data (should have numbers)
        has_numbers = any(df.apply(lambda col: col.astype(str).str.contains(r'\d{1,3}(?:,\d{3})*', regex=True).any()).values)
        
        # Should have at least 2 indicators and numeric data
        return indicator_count >= 2 and has_numbers
    
    def clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean the extracted DataFrame"""
        # Remove completely empty rows and columns
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        
        # Reset index
        df = df.reset_index(drop=True)
        
        # Clean column names if first row looks like headers
        if len(df) > 0:
            # Check if first row contains mostly text (headers)
            first_row = df.iloc[0].astype(str)
            if sum(not val.replace(',', '').replace('.', '').replace('-', '').replace('(', '').replace(')', '').strip().isdigit() 
                   for val in first_row if val and val.lower() != 'nan') > len(df.columns) / 2:
                # Use first row as headers
                df.columns = [str(col).strip() if col and str(col).lower() != 'nan' else f'Column_{i}' 
                             for i, col in enumerate(df.iloc[0])]
                df = df.iloc[1:]
                df = df.reset_index(drop=True)
        
        # Fill NaN with empty strings for better JSON output
        df = df.fillna('')
        
        return df
    
    def extract_statement_from_pdf(self, pdf_path: Path) -> Dict:
        """Extract all financial statements from a PDF using Camelot"""
        statements = {
            'balance_sheet': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'income_statement': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'cash_flow': {'tables': [], 'title': None, 'units': None, 'pages': []},
            'equity_changes': {'tables': [], 'title': None, 'units': None, 'pages': []}
        }
        
        try:
            logger.info(f"  Extracting tables with Camelot (this may take a moment)...")
            
            # Extract all tables from PDF using lattice mode (better for bordered tables)
            # Use stream mode as fallback
            try:
                tables = camelot.read_pdf(
                    str(pdf_path), 
                    pages='all', 
                    flavor='lattice',
                    line_scale=40  # Adjust for better line detection
                )
                logger.info(f"  Found {len(tables)} tables using lattice mode")
            except Exception as e:
                logger.warning(f"  Lattice mode failed, trying stream mode: {e}")
                tables = camelot.read_pdf(
                    str(pdf_path), 
                    pages='all', 
                    flavor='stream',
                    edge_tol=50
                )
                logger.info(f"  Found {len(tables)} tables using stream mode")
            
            # Process each table
            for idx, table in enumerate(tables):
                try:
                    page_num = table.page
                    df = table.df
                    
                    # Get text from the page for context
                    # Camelot doesn't provide page text, so we'll use the table data itself
                    table_text = ' '.join(df.astype(str).values.flatten())
                    
                    # Identify statement type
                    statement_type = self.identify_statement_type(table_text)
                    
                    if statement_type:
                        # Verify it's actually a financial table
                        if self.is_financial_table(df, statement_type):
                            logger.info(f"  Found {statement_type} on page {page_num} (table {idx+1})")
                            
                            # Extract metadata if not already set
                            if not statements[statement_type]['title']:
                                statements[statement_type]['title'] = self.extract_table_title(table_text, statement_type)
                            
                            if not statements[statement_type]['units']:
                                statements[statement_type]['units'] = self.extract_units(table_text)
                            
                            # Clean and store the DataFrame
                            cleaned_df = self.clean_dataframe(df)
                            if not cleaned_df.empty:
                                statements[statement_type]['tables'].append(cleaned_df)
                                statements[statement_type]['pages'].append(page_num)
                
                except Exception as e:
                    logger.warning(f"  Error processing table {idx+1}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"  Error processing {pdf_path}: {e}")
            return None
        
        return statements
    
    def merge_statement_tables(self, tables: List[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Merge multiple tables for the same statement"""
        if not tables:
            return None
        
        if len(tables) == 1:
            return tables[0]
        
        try:
            # Try to concatenate tables vertically
            merged = pd.concat(tables, ignore_index=True)
            return merged
        except Exception as e:
            logger.warning(f"  Could not merge tables: {e}")
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
        
        logger.info(f"  ✓ Saved {output_path.name}")
        return True
    
    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF and extract financial statements"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem
        
        # Check if already processed
        output_files = {
            'balance_sheet': ticker_dir / f"{base_name}-balance-sheet.json",
            'income_statement': ticker_dir / f"{base_name}-income-statement.json",
            'cash_flow': ticker_dir / f"{base_name}-cash-flow.json",
            'equity_changes': ticker_dir / f"{base_name}-equity-changes.json"
        }
        
        if not force_reprocess and all(f.exists() for f in output_files.values()):
            logger.info(f"⊘ Already processed: {pdf_path.name} (use --force to reprocess)")
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
        """Get all PDF files in the reports directory"""
        pdfs = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name != '.git':
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
                logger.error(f"✗ Failed to process {pdf_path}: {e}")
                summary['failed'] += 1
        
        return summary
    
    def run(self, batch_size: int = 10, force_reprocess: bool = False, 
            batch_number: Optional[int] = None):
        """Main execution"""
        start_time = datetime.now()
        
        logger.info("\n" + "="*70)
        logger.info("FINANCIAL STATEMENTS EXTRACTOR (Camelot)")
        logger.info("="*70)
        logger.info(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get PDFs to process
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
        
        # Process the batch
        summary = self.process_batch(pdfs_batch, force_reprocess)
        
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
    parser = argparse.ArgumentParser(
        description='Extract financial statements from PDFs using Camelot'
    )
    parser.add_argument('--batch', type=int, default=None,
                       help='Batch number to process')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='Number of PDFs per batch')
    parser.add_argument('--force', action='store_true',
                       help='Force reprocess all PDFs')
    
    args = parser.parse_args()
    
    extractor = FinancialStatementsExtractor(base_dir="reports")
    extractor.run(
        batch_size=args.batch_size,
        force_reprocess=args.force,
        batch_number=args.batch
    )


if __name__ == '__main__':
    main()
