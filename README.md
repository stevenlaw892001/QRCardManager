# QRCardManager

A web application built with Flask and Bootstrap 5 for managing business cards and generating QR codes.

## Features
- User authentication with bcrypt password hashing
- QR code generation for business card details
- Search, edit, copy, and download business card records
- Admin user management (add, edit, delete users)
- Responsive UI with Bootstrap 5
- SQL Server database integration

## Installation
1. Clone the repository: `git clone https://github.com/<your-username>/QRCardManager`
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env` (see `.env.example`)
4. Run the application: `python app.py`

## Tech Stack
- Python
- Flask
- Bootstrap 5
- SQL Server (pyodbc)
- QRCode (Python library)
- bcrypt

## License
MIT License
