import os
import time
import email
import base64
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from litellm import completion
from supabase import create_client, Client

# Load environment variables first
load_dotenv()

# Set OpenAI API Key before importing litellm
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")
if not os.environ["OPENAI_API_KEY"]:
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please set it in your .env file")

# Configuration
EMAIL_ADDRESS = "lavishsaluja.ls@gmail.com"
MAX_EMAILS_TO_PROCESS = 10  # Maximum emails to process in one-time scan
CHECK_FREQUENCY = 10  # seconds between checks in live mode
OPENAI_MODEL = "gpt-3.5-turbo"  # Model to use for analysis
SUPABASE_TABLE = "lavish_emails_tracking"  # Supabase table name

# Gmail API scopes
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# File paths
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

# Email analysis prompt
EMAIL_ANALYSIS_PROMPT = """
Email Details:
Subject: {subject}
From: {sender_name} <{sender_email}>
Date: {date}
Content: {content}

things about me and my work:
I am Lavish, 26 year old Male, I work as the co-founder of a startup "Soma AI" where we are building AI agents for financial services operations like insurance brokers operations, carriers, AML operations, banking operations and we are also evaluating and exploring more opportunities across other verticals in knowledge worker fields.
I love to stay updated with all things latest in AI, startups and technology.
I am an avid twitter user and I currently live in Bangalore, India.

you are an email assistant with access to my email inbox. your task is to help me manage my inbox by deciding to archive emails which I do not want to spend my time readig.

archive emails when the email is:
1. archive if it is promotional email or cold product launch email which has nothing to do with my work persona shared above.
2. archive if it is a credit card transaction email or statement email.
3. archive if it is a bank account debit message.
4. archive if it is a google calendar invite accpeted email. keep the declined, cancelled, modified emails.


Return ONLY this JSON:
{{"should_archive": true/false}}"""

VERBOSE = True  # Toggle detailed logging

def log(message: str, verbose: bool = False) -> None:
    """Unified logging function"""
    if verbose and not VERBOSE:
        return
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

class PersonalEmailReader:
    def __init__(self):
        self.service = self._initialize_gmail_service()
        self.last_check_time = datetime.now() - timedelta(hours=1)
        
        # Initialize Supabase
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)

    def _get_credentials(self):
        """Get valid credentials for Gmail API"""
        creds = None

        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            except Exception as e:
                print(f"Error loading existing credentials: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Error refreshing credentials: {e}")
                    creds = None
            
            if not creds:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        CREDENTIALS_FILE,
                        SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"Error during authentication flow: {e}")
                    raise

            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

        return creds

    def _initialize_gmail_service(self) -> any:
        """Initialize Gmail API service"""
        try:
            print("\n🚀 Starting Gmail service initialization...")
            creds = self._get_credentials()
            service = build("gmail", "v1", credentials=creds)
            print("✅ Gmail service initialized successfully!")
            return service
        except Exception as e:
            print(f"❌ Gmail service initialization failed: {e}")
            raise

    def get_recent_messages(self, live_mode: bool = False) -> List[Dict]:
        """Fetch messages based on mode"""
        try:
            params = {
                "userId": "me",
            }
            
            if live_mode:
                # Live mode: unread emails from last 24h
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
                params.update({
                    "labelIds": ['INBOX', 'UNREAD'],
                    "q": f"after:{yesterday}"
                })
            else:
                # One-time scan mode
                params.update({
                    "maxResults": MAX_EMAILS_TO_PROCESS
                })
                
            return self.service.users().messages().list(**params).execute().get('messages', [])
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []

    def _extract_email_content(self, message: Dict) -> tuple:
        """Extract email content using Gmail API, focusing on text/plain parts"""
        try:
            # Extract headers
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
            
            # Parse sender info
            if '<' in from_header and '>' in from_header:
                sender_name = from_header.split('<')[0].strip()
                sender_email = from_header.split('<')[1].split('>')[0].strip()
            else:
                sender_name = ''
                sender_email = from_header.strip()

            # Get plain text content
            content = ""
            parts = message['payload'].get('parts', [])
            
            # First try to find text/plain in parts
            for part in parts:
                if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                    content = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                    break
            
            # If no text/plain found in parts, check main body
            if not content and 'body' in message['payload'] and 'data' in message['payload']['body']:
                content = base64.urlsafe_b64decode(message['payload']['body']['data']).decode('utf-8', errors='ignore')

            # Clean and limit content
            content = ' '.join(content.split())  # Remove extra whitespace
            words = content.split()
            if len(words) > 1000:
                log(f"⚠️  Truncating email content from {len(words)} to 1000 words", verbose=True)
                content = ' '.join(words[:1000])
            
            return subject, sender_name, sender_email, date, content.strip()
            
        except Exception as e:
            log(f"❌ Error extracting content: {e}")
            return '', '', '', '', ''

    def analyze_email(self, subject: str, sender_name: str, sender_email: str, date: str, content: str) -> Dict:
        """Analyze email using LiteLLM"""
        try:
            # Verify API key is set
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OpenAI API key is not set or invalid")
            
            prompt = EMAIL_ANALYSIS_PROMPT.format(
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                date=date,
                content=content
            )

            response = completion(
                model="gpt-3.5-turbo",
                messages=[{
                    "role": "system",
                    "content": "You are a JSON-only response bot. Always respond with valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0.3
            )
            
            response_text = response.choices[0].message.content.strip()
            # Clean the response to ensure it's valid JSON
            response_text = response_text[response_text.find('{'):response_text.rfind('}')+1]
            
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                log(f"❌ Invalid JSON response: {response_text}")
                return None

        except Exception as e:
            log(f"❌ Error analyzing email: {e}")
            return None

    def archive_email(self, message_id: str) -> bool:
        """Archive an email by removing INBOX label and marking as read"""
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={
                    'removeLabelIds': ['INBOX', 'UNREAD'],
                    'addLabelIds': []
                }
            ).execute()
            return True
        except Exception as e:
            print(f"Error archiving message: {e}")
            return False

    def is_email_processed(self, message_id: str) -> bool:
        """Check if email has been processed before"""
        try:
            response = (
                self.supabase.table("lavish_emails_tracking")
                .select("*")
                .eq("email_message_id", message_id)
                .execute()
            )
            return len(response.data) > 0
        except Exception as e:
            print(f"Error checking email status: {e}")
            return False

    def track_email_processing(self, message_id: str, status: str) -> None:
        """Record email processing in Supabase"""
        try:
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    response = self.supabase.table("lavish_emails_tracking").insert({
                        "email_message_id": message_id,
                        "processing_status": status
                    }).execute()
                    
                    if response and hasattr(response, 'data'):
                        log(f"💾 Tracked email status: {status}", verbose=True)
                        return
                    
                except Exception as inner_e:
                    retry_count += 1
                    if retry_count == max_retries:
                        raise inner_e
                    log(f"⚠️  Retry {retry_count}/{max_retries}: {inner_e}", verbose=True)
                    time.sleep(1)
                    
        except Exception as e:
            log(f"❌ Error tracking email: {e}")

    def process_message(self, message_id: str) -> None:
        """Process a single email message"""
        try:
            # Check if already processed
            if self.is_email_processed(message_id):
                log(f"⏭️  Skipping message {message_id} - already processed")
                return

            # Get message details
            message = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format='full'
            ).execute()
            
            # Extract content
            subject, sender_name, sender_email, date, content = self._extract_email_content(message)
            
            # Log email details
            log("\n📧 Email Details:")
            log(f"   From: {sender_name} <{sender_email}>")
            log(f"   Subject: {subject}")
            log(f"   Date: {date}")
            log(f"   Content Length: {len(content)} chars", verbose=True)
            
            # Get archival decision
            log("🤔 Analyzing email...")
            analysis = self.analyze_email(subject, sender_name, sender_email, date, content)
            
            if analysis and analysis.get('should_archive'):
                log("📥 Decision: Archive")
                if self.archive_email(message_id):
                    log("✅ Archived successfully")
                    self.track_email_processing(message_id, "archived")
                else:
                    log("❌ Archive failed")
                    self.track_email_processing(message_id, "archive_failed")
            else:
                log("📌 Decision: Keep")
                self.track_email_processing(message_id, "kept")
                
        except Exception as e:
            log(f"❌ Error processing message: {e}")
            self.track_email_processing(message_id, "error")

    def run(self, live_mode: bool = False) -> None:
        """Process emails based on mode"""
        log(f"\n{'='*50}")
        log(f"Starting Email Processor in {'LIVE' if live_mode else 'ONE-TIME'} mode")
        log(f"{'='*50}\n")
        
        while True:
            try:
                messages = self.get_recent_messages(live_mode=live_mode)
                log(f"Found {len(messages)} emails to process")
                
                for idx, message in enumerate(messages, 1):
                    log(f"\n[{idx}/{len(messages)}] Processing next email...")
                    self.process_message(message['id'])
                
                if not live_mode:
                    log("\n✅ One-time scan completed!")
                    break
                
                log(f"\n💤 Waiting {CHECK_FREQUENCY}s before next check...", verbose=True)
                time.sleep(CHECK_FREQUENCY)
                    
            except Exception as e:
                log(f"❌ Error in main loop: {e}")
                if not live_mode:
                    break
                time.sleep(CHECK_FREQUENCY)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Email processing script')
    parser.add_argument('--live', action='store_true', help='Run in live mode to continuously scan inbox')
    args = parser.parse_args()
    
    reader = PersonalEmailReader()
    reader.run(live_mode=args.live) 