import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")  # optional; for JWT verify
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# Email provider configuration
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "none")  # e.g. resend|sendgrid|none
EMAIL_FROM_DOMAIN = os.getenv("EMAIL_FROM_DOMAIN", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")  # for EMAIL_PROVIDER=resend
INBOUND_WEBHOOK_SECRET = os.getenv("INBOUND_WEBHOOK_SECRET", "")  # optional; for inbound email webhook

# Jina Reader base URL (no key required)
JINA_READER_URL = "https://r.jina.ai/"
