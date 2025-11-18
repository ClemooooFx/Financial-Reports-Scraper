# NSE Financial Reports Scraper

Automated scraper for downloading financial reports of companies listed on the Nairobi Securities Exchange (NSE).

## Features

- Scrapes all company tickers from NSE
- Downloads annual reports, interim reports, and abridged reports
- Organizes files by ticker symbol
- Saves metadata for each document
- Automated quarterly runs via GitHub Actions

## Project Structure

```
.
├── .github/
│   └── workflows/
│       └── scraper.yml          # GitHub Actions workflow
├── reports/                      # Downloaded reports directory
│   ├── ABSA/
│   │   ├── 2024-ar-00.pdf
│   │   ├── 2024-ar-00.json      # Metadata
│   │   ├── 2024-ir-hy.pdf
│   │   └── 2024-ir-hy.json
│   ├── EQTY/
│   └── ...
├── scraper.py                    # Main scraper script
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

## Setup

### Local Development

1. Clone the repository:
```bash
git clone <your-repo-url>
cd nse-reports-scraper
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the scraper:
```bash
python scraper.py
```

### GitHub Actions Setup

1. Push this repository to GitHub

2. Enable GitHub Actions in your repository settings

3. The scraper will automatically run on:
   - February 15 at 2 AM UTC
   - May 15 at 2 AM UTC
   - August 15 at 2 AM UTC
   - November 15 at 2 AM UTC

4. You can also manually trigger the workflow:
   - Go to Actions tab
   - Select "NSE Financial Reports Scraper"
   - Click "Run workflow"

## Configuration

### Modify Schedule

Edit `.github/workflows/scraper.yml` to change the schedule:

```yaml
schedule:
  - cron: '0 2 15 2,5,8,11 *'  # Mid-quarter runs
```

Cron format: `minute hour day month day-of-week`

### Scrape Specific Tickers

Modify `scraper.py` to scrape only specific tickers:

```python
if __name__ == "__main__":
    scraper = NSEReportsScraper()
    # Scrape specific tickers
    scraper.run(specific_tickers=['ABSA', 'EQTY', 'KCB'])
```

## How It Works

1. **Fetch Tickers**: Scrapes https://afx.kwayisi.org/nse/ for all listed company tickers

2. **Navigate to Company Pages**: For each ticker, constructs URL: `https://africanfinancials.com/company/ke-{ticker}/`

3. **Find Documents Tab**: Locates the unique "Documents & Reports" tab ID for each company

4. **Extract Document Links**: Parses the documents table to get all available reports

5. **Download PDFs**: Extracts Google Drive links from document pages and downloads PDFs

6. **Save Metadata**: Stores document metadata (type, year, period, date) as JSON

## File Naming Convention

Files are named using the format from the source URL:
- `2024-ar-00.pdf` - Annual Report 2024
- `2024-ir-hy.pdf` - Interim Report 2024 Half Year
- `2025-ab-00.pdf` - Abridged Report 2025

## Metadata Format

Each PDF has an accompanying JSON file with metadata:

```json
{
  "ticker": "UNGA",
  "type": "Annual Report",
  "year": "2024",
  "period": "",
  "date": "2025-05-27",
  "source_url": "https://africanfinancials.com/document/ke-unga-2024-ar-00/"
}
```

## Error Handling

- Skips tickers without a Documents & Reports tab
- Continues processing other tickers if one fails
- Skips already downloaded files
- Logs errors for debugging

## Rate Limiting

The scraper includes delays to be respectful to servers:
- 2 seconds between document downloads
- 3 seconds between ticker processing

## Contributing

Feel free to submit issues or pull requests for improvements.

## License

MIT License

## Disclaimer

This scraper is for educational and research purposes. Please respect the terms of service of the websites being scraped and ensure you have permission to download and use the financial reports.
