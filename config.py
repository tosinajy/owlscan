# config.py

class Config:
    # IMPORTANT: Replace 'auditor_user', 'your_password', and 'website_auditor'
    # with your actual MySQL database credentials.
    SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://root:vaug@localhost/owlscan'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'a-very-secret-key-for-sessions' # Used for flash messages