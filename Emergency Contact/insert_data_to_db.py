from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Step 1: Define the Model
class EmergencyNumber(db.Model):
    __tablename__ = 'emergency_numbers'
    
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(255), nullable=False)
    police = db.Column(db.String(255))
    ambulance = db.Column(db.String(255))
    fire = db.Column(db.String(255))
    notes = db.Column(db.Text)

# Step 2: Insert Data into the Database
def insert_data(df):
    for index, row in df.iterrows():
        emergency_number = EmergencyNumber(
            country=row['Country'],
            police=row['Police'],
            ambulance=row['Ambulance'],
            fire=row['Fire'],
            notes=row['Notes']
        )
        db.session.add(emergency_number)
    
    db.session.commit()

# Assuming 'df' is your cleaned DataFrame
insert_data(df)

print("Data has been inserted into the PostgreSQL database using Flask SQLAlchemy.")
