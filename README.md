## Gmail Auto-Archiver

Automatically process and archive emails based on custom rules using GPT.

### Required Files
- `main.py` - Main script
- `.env` - Environment variables
- `credentials.json` - Gmail API credentials (obtain from Google Cloud Console)
- `requirements.txt` - Python dependencies

### Environment Variables (.env)
```
OPENAI_API_KEY=your_openai_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

### Setup
1. Install dependencies:
```bash
pip install -r requirements.txt
```
2. Set up `.env` file with required credentials
3. Place `credentials.json` in root directory

### Usage Modes
1. One-time Scan Mode:
```bash
python main.py
```
Processes up to 10 most recent emails once and exits.

2. Live Mode:
```bash
python main.py --live
```
Continuously monitors inbox every 10 seconds for new unread emails from last 24 hours.
