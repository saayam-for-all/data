import argparse

from utils import seed_all
from generate_users import generate_users
from generate_fraud_requests_notifications import generate_fraud_requests, generate_notifications


def main():
    parser = argparse.ArgumentParser(description='Generate mock data for Saayam DB tables')
    parser.add_argument('--users', type=int, default=100, help='Number of users (default: 100)')
    parser.add_argument('--fraud', type=int, default=100, help='Number of fraud requests (default: 100)')
    parser.add_argument('--notifications', type=int, default=100, help='Number of notifications (default: 100)')
    args = parser.parse_args()

    seed_all(42)

    users_df = generate_users(count=args.users)
    generate_fraud_requests(users_df, count=args.fraud)
    generate_notifications(users_df, count=args.notifications)

    print('Done.')


if __name__ == '__main__':
    main()