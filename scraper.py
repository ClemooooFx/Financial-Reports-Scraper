import requests
from bs4 import BeautifulSoup
import os
import time
import re
from pathlib import Path
from urllib.parse import urljoin
import json

class NSEReportsScraper:
    def __init__(self, base_dir="reports"):
        self.nse_url = "https://afx.kwayisi.org/nse/"
        self.africanfinancials_base = "https://africanfinancials.com/company/ke-"
        self.base_dir = base_dir
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def get_tickers(self):
        """Scrape all tickers from NSE page"""
        print("Fetching tickers from NSE...")
        response = self.session.get(self.nse_url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        tickers = []
        table = soup.find('table')
        if table:
            rows = table.find('tbody').find_all('tr')
            for row in rows:
                first_td = row.find('td')
                if first_td:
                    link = first_td.find('a')
                    if link:
                        ticker = link.text.strip()
                        tickers.append(ticker)
        
        print(f"Found {len(tickers)} tickers: {tickers}")
        return tickers
    
    def get_documents_tab_id(self, ticker):
        """Get the unique tab ID for Documents & Reports section"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/"
        print(f"Fetching tab ID for {ticker} from {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the Documents & Reports tab
            tabs = soup.find_all('a', class_='tab-link')
            for tab in tabs:
                if 'Documents & Reports' in tab.get_text():
                    href = tab.get('href', '')
                    if href.startswith('#tab-'):
                        tab_id = href[1:]  # Remove the '#'
                        print(f"Found tab ID for {ticker}: {tab_id}")
                        return tab_id
            
            print(f"No Documents & Reports tab found for {ticker}")
            return None
            
        except Exception as e:
            print(f"Error fetching tab ID for {ticker}: {e}")
            return None
    
    def get_document_links(self, ticker, tab_id):
        """Get all document links from the Documents & Reports tab"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/#{tab_id}"
        print(f"Fetching documents for {ticker} from {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            documents = []
            table = soup.find('table', id='af21_prices')
            
            if not table:
                print(f"No documents table found for {ticker}")
                return documents
            
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
                for row in rows:
                    tds = row.find_all('td')
                    if len(tds) >= 4:
                        # Get the first link in the row (they all go to same place)
                        link_tag = tds[0].find('a')
                        if link_tag:
                            doc_url = link_tag.get('href')
                            doc_type = link_tag.get_text(strip=True)
                            
                            year = tds[1].get_text(strip=True)
                            period = tds[2].get_text(strip=True)
                            date = tds[3].get_text(strip=True)
                            
                            # Extract filename from URL
                            # e.g., https://africanfinancials.com/document/ke-xprs-2024-ir-hy/
                            match = re.search(r'/document/(ke-[^/]+)/', doc_url)
                            if match:
                                filename = match.group(1)
                                # Remove 'ke-' prefix and extract meaningful part
                                filename = filename.replace(f'ke-{ticker.lower()}-', '')
                                
                                documents.append({
                                    'url': doc_url,
                                    'type': doc_type,
                                    'year': year,
                                    'period': period,
                                    'date': date,
                                    'filename': filename
                                })
            
            print(f"Found {len(documents)} documents for {ticker}")
            return documents
            
        except Exception as e:
            print(f"Error fetching documents for {ticker}: {e}")
            return []
    
    def extract_pdf_url(self, doc_url):
        """Extract Google Drive PDF URL from document page"""
        try:
            response = self.session.get(doc_url, timeout=30)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find iframe with Google Drive link
            iframe = soup.find('iframe', {'src': re.compile(r'drive\.google\.com')})
            if iframe:
                drive_url = iframe.get('src')
                # Convert preview URL to direct download URL
                # From: https://drive.google.com/file/d/FILE_ID/preview
                # To: https://drive.google.com/uc?export=download&id=FILE_ID
                match = re.search(r'/d/([^/]+)/', drive_url)
                if match:
                    file_id = match.group(1)
                    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                    return download_url
            
            return None
            
        except Exception as e:
            print(f"Error extracting PDF URL from {doc_url}: {e}")
            return None
    
    def download_pdf(self, pdf_url, output_path):
        """Download PDF from Google Drive"""
        try:
            print(f"Downloading PDF to {output_path}...")
            
            # First request
            response = self.session.get(pdf_url, stream=True, timeout=60)
            
            # Handle Google Drive's virus scan warning page
            if 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.content, 'html.parser')
                download_link = soup.find('a', {'id': 'uc-download-link'})
                if download_link:
                    confirm_url = download_link.get('href')
                    if not confirm_url.startswith('http'):
                        confirm_url = 'https://drive.google.com' + confirm_url
                    response = self.session.get(confirm_url, stream=True, timeout=60)
            
            # Save the file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            print(f"Successfully downloaded: {output_path}")
            return True
            
        except Exception as e:
            print(f"Error downloading PDF from {pdf_url}: {e}")
            return False
    
    def scrape_ticker(self, ticker):
        """Scrape all documents for a single ticker"""
        print(f"\n{'='*60}")
        print(f"Processing ticker: {ticker}")
        print(f"{'='*60}")
        
        # Create ticker directory
        ticker_dir = Path(self.base_dir) / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        
        # Get the documents tab ID
        tab_id = self.get_documents_tab_id(ticker)
        if not tab_id:
            print(f"Skipping {ticker} - no documents tab found")
            return
        
        # Get all document links
        documents = self.get_document_links(ticker, tab_id)
        
        # Download each document
        for doc in documents:
            print(f"\nProcessing: {doc['type']} - {doc['year']} - {doc['period']}")
            
            # Extract PDF URL from document page
            pdf_url = self.extract_pdf_url(doc['url'])
            if not pdf_url:
                print(f"Could not find PDF URL for {doc['url']}")
                continue
            
            # Download PDF
            output_filename = f"{doc['filename']}.pdf"
            output_path = ticker_dir / output_filename
            
            if output_path.exists():
                print(f"File already exists: {output_path}")
                continue
            
            success = self.download_pdf(pdf_url, output_path)
            if success:
                # Save metadata
                metadata = {
                    'ticker': ticker,
                    'type': doc['type'],
                    'year': doc['year'],
                    'period': doc['period'],
                    'date': doc['date'],
                    'source_url': doc['url']
                }
                metadata_path = ticker_dir / f"{doc['filename']}.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            
            # Be nice to the server
            time.sleep(2)
    
    def run(self, specific_tickers=None):
        """Run the scraper for all tickers or specific ones"""
        tickers = specific_tickers if specific_tickers else self.get_tickers()
        
        print(f"\nStarting scraper for {len(tickers)} tickers...")
        print(f"Output directory: {self.base_dir}")
        
        for i, ticker in enumerate(tickers, 1):
            print(f"\n[{i}/{len(tickers)}] Processing {ticker}...")
            try:
                self.scrape_ticker(ticker)
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
            
            # Delay between tickers
            if i < len(tickers):
                time.sleep(3)
        
        print("\n" + "="*60)
        print("Scraping completed!")
        print("="*60)

if __name__ == "__main__":
    scraper = NSEReportsScraper()
    scraper.run()
