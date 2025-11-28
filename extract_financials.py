"""
Financial Statements Extractor with AI
Uses Claude API to intelligently extract financial statements from PDFs
"""

import json
from pathlib import Path
from datetime import datetime
import argparse
from typing import Dict, List, Optional
import logging
import base64
import os
from anthropic import Anthropic

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AIFinancialExtractor:
    def __init__(self, base_dir="reports", api_key=None):
        self.base_dir = Path(base_dir)
        
        # Get API key from environment or parameter
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY environment variable.")
        
        self.client = Anthropic(api_key=self.api_key)
        
        # Extraction prompt
        self.extraction_prompt = """You are a financial data extraction expert. Extract the following FOUR main financial statements from this PDF:

1. **Balance Sheet** (also called Statement of Financial Position)
2. **Income Statement** (also called Statement of Profit or Loss, Statement of Comprehensive Income, or P&L)
3. **Cash Flow Statement** (also called Statement of Cash Flows)
4. **Statement of Changes in Equity**

For EACH statement you find, extract:
- The EXACT table title as it appears in the document
- The unit of measurement (e.g., "Shs'million", "thousands", "KShs '000", etc.)
- ALL row items with their labels (preserve exact wording)
- ALL column headers (usually years like 2024, 2023, etc.)
- ALL numerical values
- The page number where the statement appears

IMPORTANT RULES:
- Include BOTH the row labels (text) AND the numerical values
- Preserve the exact structure and hierarchy of the table
- Include subtotals, totals, and section headers
- If a statement spans multiple pages, combine them
- If a value is in parentheses like (1,234), keep the parentheses (it means negative)
- Ignore other tables that are NOT one of these 4 main statements
- If you can't find a particular statement, return null for that statement

Return your response as a JSON object with this structure:
{
  "balance_sheet": {
    "title": "exact title from document",
    "units": "unit of measurement",
    "pages": [page numbers],
    "columns": ["column headers"],
    "rows": [
      {
        "label": "row label",
        "indent_level": 0,
        "values": {"2024": "value", "2023": "value"}
      }
    ]
  },
  "income_statement": { same structure },
  "cash_flow": { same structure },
  "equity_changes": { same structure }
}

If a statement is not found, use null instead of the object."""

    def pdf_to_base64(self, pdf_path: Path) -> str:
        """Convert PDF to base64"""
        with open(pdf_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def extract_with_claude(self, pdf_path: Path) -> Optional[Dict]:
        """Use Claude to extract financial statements from PDF"""
        try:
            logger.info(f"Reading PDF: {pdf_path.name}")
            pdf_data = self.pdf_to_base64(pdf_path)
            
            # Check file size (Claude has limits)
            file_size_mb = len(pdf_data) / (1024 * 1024)
            if file_size_mb > 30:
                logger.warning(f"PDF too large ({file_size_mb:.1f}MB). May fail or be truncated.")
            
            logger.info(f"Sending to Claude API ({file_size_mb:.1f}MB)...")
            
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16000,  # Increase for large statements
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_data
                                }
                            },
                            {
                                "type": "text",
                                "text": self.extraction_prompt
                            }
                        ]
                    }
                ]
            )
            
            # Parse Claude's response
            response_text = message.content[0].text
            
            # Extract JSON from response (Claude might include explanation text)
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.error("No JSON found in Claude's response")
                return None
            
            json_str = response_text[json_start:json_end]
            extracted_data = json.loads(json_str)
            
            return extracted_data
        
        except Exception as e:
            logger.error(f"Error extracting from {pdf_path}: {e}")
            return None
    
    def save_statement(self, statement_data: Dict, output_path: Path) -> bool:
        """Save extracted statement as JSON"""
        if not statement_data or statement_data is None:
            return False
        
        try:
            # Add extraction metadata
            statement_data['extracted_at'] = datetime.now().isoformat()
            statement_data['extractor'] = 'Claude AI'
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(statement_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✓ Saved {output_path.name}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving {output_path}: {e}")
            return False
    
    def process_pdf(self, pdf_path: Path, force_reprocess: bool = False) -> Dict:
        """Process a single PDF and extract financial statements"""
        ticker_dir = pdf_path.parent
        base_name = pdf_path.stem
        
        # Define output files
        output_files = {
            'balance_sheet': ticker_dir / f"{base_name}-balance-sheet.json",
            'income_statement': ticker_dir / f"{base_name}-income-statement.json",
            'cash_flow': ticker_dir / f"{base_name}-cash-flow.json",
            'equity_changes': ticker_dir / f"{base_name}-equity-changes.json"
        }
        
        # Check if already processed
        if not force_reprocess and all(f.exists() for f in output_files.values()):
            logger.info(f"⊙ Already processed: {pdf_path.name}")
            return {'skipped': True, 'reason': 'already_processed'}
        
        logger.info(f"\n{'='*70}")
        logger.info(f"Processing: {pdf_path.name}")
        logger.info(f"{'='*70}")
        
        # Extract with Claude
        extracted_data = self.extract_with_claude(pdf_path)
        
        if not extracted_data:
            logger.error(f"✗ Extraction failed for {pdf_path.name}")
            return {'skipped': True, 'reason': 'extraction_failed'}
        
        # Save each statement
        results = {}
        for statement_type, statement_data in extracted_data.items():
            output_path = output_files[statement_type]
            success = self.save_statement(statement_data, output_path)
            results[statement_type] = success
        
        return results
    
    def get_all_pdfs(self) -> List[Path]:
        """Get all PDF files in the reports directory"""
        pdfs = []
        for ticker_dir in sorted(self.base_dir.iterdir()):
            if ticker_dir.is_dir() and ticker_dir.name not in ['.git', '__pycache__']:
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
                'balance_sheet': 0,
                'income_statement': 0,
                'cash_flow': 0,
                'equity_changes': 0
            }
        }
        
        for i, pdf_path in enumerate(pdfs, 1):
            logger.info(f"\n[{i}/{len(pdfs)}]")
            
            try:
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
        
        print("\n" + "🤖 "*35)
        print("AI FINANCIAL STATEMENTS EXTRACTOR")
        print("🤖 "*35)
        logger.info(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Using: Claude Sonnet 4")
        
        # Get PDFs to process
        if batch_number:
            pdfs_batch = self.get_pdf_batch(batch_number, batch_size, force_reprocess)
            if not pdfs_batch:
                logger.info(f"No PDFs in batch {batch_number}")
                return
        else:
            if force_reprocess:
                logger.info("Mode: Force reprocess ALL PDFs")
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
            'extractor': 'Claude AI (Sonnet 4)',
            'total_pdfs': summary['total'],
            'successful': summary['successful'],
            'skipped': summary['skipped'],
            'failed': summary['failed'],
            'statements_extracted': summary['statements_extracted']
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
        print(f"\nStatements Extracted:")
        for stmt_type, count in total_summary['statements_extracted'].items():
            print(f"  {stmt_type:20s}: {count}")
        print(f"\nDuration:      {duration}")
        print(f"Summary saved: {summary_path}")
        print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Extract financial statements using Claude AI'
    )
    parser.add_argument('--batch', type=int, default=None,
                       help='Batch number to process')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='Number of PDFs per batch (default: 10)')
    parser.add_argument('--force', action='store_true',
                       help='Force reprocess all PDFs')
    parser.add_argument('--api-key', type=str, default=None,
                       help='Anthropic API key (or set ANTHROPIC_API_KEY env var)')
    
    args = parser.parse_args()
    
    try:
        extractor = AIFinancialExtractor(
            base_dir="reports",
            api_key=args.api_key
        )
        extractor.run(
            batch_size=args.batch_size,
            force_reprocess=args.force,
            batch_number=args.batch
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.info("\nTo use this extractor, you need an Anthropic API key.")
        logger.info("Get one at: https://console.anthropic.com/")
        logger.info("Then either:")
        logger.info("  1. Set environment variable: export ANTHROPIC_API_KEY='your-key'")
        logger.info("  2. Pass as argument: python extract_financials.py --api-key 'your-key'")


if __name__ == '__main__':
    main()
