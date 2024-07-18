#Main logic and function of fraud detection

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URI

#Set up the database connection
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)

def check_user_request_count(user_id):
    # 30mins, request id, 
    session = Session()
    query = text("SELECT COUNT(*) FROM requests WHERE user_id = :user_id")
    result = session.execute(query, {'user_id': user_id}).scalar()
    session.close()
    return result
    # return True
    
def is_fraudulent_request(user_id, request_location, request_count):
    # db_request_count = check_user_request_count(user_id)
    # test override
    db_request_count = request_count
    is_fraud = False
    reason = "No fraud detected"

    if db_request_count > 5:
        is_fraud = True
        reason = "Exceeded request limit in database"

    if user_id == 'known_fraudster':
        is_fraud = True
        reason = "User is a known fraudster"

    return is_fraud, reason


# international message
#loc parameter
