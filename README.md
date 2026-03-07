# Testagent (analysis agent 1 ) - Procurement Analysis System

## Overview
AI-powered procurement analysis system that extracts structured information from requester emails using Claude Sonnet 4 via AWS Bedrock.

## Project Structure
```
testagent/
├── agents/
│   └── analysis/
│       ├── __init__.py
│       └── agent.py          # Analysis Agent - extracts ProcurementSpec
├── email_gateway/
│   ├── __init__.py
│   ├── parser.py             # MIME email parser
│   ├── poller.py             # Gmail IMAP poller
│   ├── router.py             # Email routing logic
│   └── sender.py             # Email sender
├── tests/
│   ├── test_analysis_agent.py
│   └── test_real_email.py    # End-to-end test with Gmail
├── config.py                  # Configuration management
├── logger.py                  # Structured JSON logging
├── requirements.txt           # Python dependencies
└── .env                       # Environment variables
```

## Setup & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Update `.env` with your credentials:
```env
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0

# Gmail Configuration
GMAIL_ADDRESS=your-email@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
```

### 3. AWS Setup
Configure AWS credentials if not using .env:
```bash
aws configure
```

## Key Components

### Configuration (`config.py`)
- Centralized configuration using Pydantic Settings
- Loads from environment variables and `.env` file
- Manages AWS, Gmail, database, and application settings

### Logger (`logger.py`)
- Structured JSON logging for all components
- Supports extra fields via `extra={}` parameter
- Configurable log level via `LOG_LEVEL` environment variable

### Analysis Agent (`agents/analysis/agent.py`)
- Extracts structured `ProcurementSpec` from free-text emails
- Supports French and English
- Returns validated procurement information:
  - Product name & category
  - Quantity & unit
  - Budget range (min/max in TND)
  - Deadline (ISO format)
  - Validation status & rejection reasons

### Email Gateway
- **Parser**: Extracts text from MIME emails, PDFs, Excel, and images (OCR)
- **Poller**: Monitors Gmail inbox using IMAP
- **Router**: Routes incoming emails to appropriate handlers
- **Sender**: Sends response emails via SMTP

## Dependencies

### Core Frameworks
- `strands-agents>=0.1.0` - Agent framework
- `boto3>=1.34.0` - AWS SDK
- `pydantic>=2.0.0` - Data validation
- `pydantic-settings>=2.0.0` - Configuration management

### Document Processing
- `pdfplumber>=0.9.0` - PDF text extraction
- `openpyxl` - Excel file parsing
- `pytesseract` - OCR for images
- `pillow>=9.5.0` - Image processing
- `beautifulsoup4` - HTML parsing

### Utilities
- `python-dotenv>=1.0.0` - Environment variable management
- `apscheduler>=3.10.0` - Email polling scheduler

## Testing

### Run Analysis Agent Test
```bash
python tests/test_analysis_agent.py
```

### Run Real Email Test
```bash
python tests/test_real_email.py
```

## Fixes Applied

### Issue 1: Missing Modules
**Problem**: Import errors for `config` and `logger` modules in `agent.py`

**Solution**: 
- Created `config.py` with Pydantic-based settings management
- Created `logger.py` with structured JSON logging

### Issue 2: Missing Dependencies
**Problem**: Multiple `ModuleNotFoundError` exceptions

**Solution**: Added all required packages to `requirements.txt`:
- Configuration: `pydantic`, `pydantic-settings`, `python-dotenv`
- Document parsing: `pdfplumber`, `openpyxl`, `pytesseract`, `pillow`, `beautifulsoup4`
- Scheduling: `apscheduler`

## Usage Example

```python
from agents.analysis.agent import AnalysisAgent

# Initialize agent
agent = AnalysisAgent()

# Analyze email
email_body = """
Bonjour,
J'ai besoin de 50 ordinateurs portables HP pour mon département.
Budget: 75000-85000 TND
Date limite: 2026-04-15
"""

spec = agent.analyze(email_body, "requester@example.com")

if spec.is_valid:
    print(f"Product: {spec.product}")
    print(f"Quantity: {spec.quantity} {spec.unit}")
    print(f"Budget: {spec.budget_min}-{spec.budget_max} TND")
    print(f"Deadline: {spec.deadline}")
else:
    print(f"Rejected: {spec.rejection_reason}")
```

## Notes

- Ensure AWS Bedrock access is enabled for Claude Sonnet 4
- Gmail requires an App Password (not regular password)
- All monetary values are in TND (Tunisian Dinar)
