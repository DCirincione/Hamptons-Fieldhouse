"""Trusted server operator tool. Never expose this operation to public sign-up."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.routes.bookings import get_booking_db

parser = argparse.ArgumentParser(description='Inspect or change an existing account’s admin permission.')
parser.add_argument('--email', required=True)
parser.add_argument('--role', choices=['admin', 'member'])
args = parser.parse_args()
db = get_booking_db(get_settings())
match = None
page = 1
while True:
    users = db.auth.admin.list_users(page=page, per_page=100)
    match = next((u for u in users if (u.email or '').casefold() == args.email.casefold()), None)
    if match or len(users) < 100:
        break
    page += 1
if not match:
    print('Account not found. Create and confirm the account on /account first.')
    sys.exit(2)
if args.role == 'admin' and not match.email_confirmed_at:
    print('Confirm this account’s email before granting admin permission.')
    sys.exit(2)
if args.role:
    db.auth.admin.update_user_by_id(match.id, {'app_metadata': {**match.app_metadata, 'role': args.role}})
    print(f'Account permission updated to {args.role}.')
else:
    print({'exists': True, 'email_confirmed': bool(match.email_confirmed_at), 'role': match.app_metadata.get('role', 'member')})
