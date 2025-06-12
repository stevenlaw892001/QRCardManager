from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
import qrcode
from PIL import Image
import pyodbc
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import bcrypt
import secrets

# Load environment variables from .env file
# Note: Ensure .env is included in .gitignore to prevent exposing sensitive data
load_dotenv()

def ensure_secret_key():
    """Generate or retrieve a secure secret key for Flask session management."""
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key:
        secret_key = secrets.token_hex(24)
        with open('.env', 'a', encoding='utf-8') as f:
            f.write(f"\nSECRET_KEY={secret_key}\n")
        load_dotenv(override=True)
    return os.getenv('SECRET_KEY')

# Initialize Flask application
app = Flask(__name__)
app.secret_key = ensure_secret_key()

# Configure session timeout to 10 minutes for security
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

# Initialize Flask-Login for user authentication
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = 'strong'

class User(UserMixin):
    """User class for Flask-Login, storing user ID, username, and role."""
    def __init__(self, userid, username, role):
        self.id = userid
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(userid):
    """Load user from database by userid for Flask-Login."""
    try:
        with NameCardManager().connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT userid, username, role FROM dbo.name_card_admin WHERE userid = ?", (userid,))
                row = cursor.fetchone()
                if row:
                    return User(row[0], row[1], row[2])
        return None
    except pyodbc.Error as e:
        print(f"Error loading user: {e}")
        return None

class NameCardManager:
    """Manages database connections, QR code generation, and data storage."""
    def __init__(self):
        # Load database configuration from environment variables
        self.db_config = {
            'server': os.getenv('DB_SERVER'),
            'database': os.getenv('DB_NAME'),
            'driver': os.getenv('DB_DRIVER'),
            'username': os.getenv('DB_USERNAME'),
            'password': os.getenv('DB_PASSWORD')
        }
        # Use environment variable for QR code storage path
        self.upload_folder = os.getenv('QR_UPLOAD_FOLDER', 'static/qr_codes')
        self.logo_path = os.getenv('LOGO_PATH', 'static/images/company_logo.png')
        os.makedirs(self.upload_folder, exist_ok=True)

    def connect_db(self):
        """Establish a connection to the SQL Server database."""
        conn_str = (
            f"DRIVER={self.db_config['driver']};"
            f"SERVER={self.db_config['server']};"
            f"DATABASE={self.db_config['database']};"
            f"UID={self.db_config['username']};"
            f"PWD={self.db_config['password']}"
        )
        return pyodbc.connect(conn_str)

    def generate_qr_code(self, data):
        """Generate a QR code from provided vCard data."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=12,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        
        # Resize QR code to 1000x1000 pixels for clarity
        target_size = 1000
        qr_img = qr_img.resize((target_size, target_size), Image.LANCZOS)
        
        return qr_img

    def escape_vcard_value(self, value):
        """Escape special characters in vCard fields to ensure valid format."""
        if value is None:
            return ''
        if not isinstance(value, str):
            value = str(value)
        return value.replace('\\', '\\\\').replace(',', '\\,').replace(';', '\\;')

    def generate_vcard(self, details):
        """Generate vCard string from name card details."""
        last_name = self.escape_vcard_value(details['staff_ename'].split(',')[0].strip()) if ',' in details['staff_ename'] else self.escape_vcard_value(details['staff_ename'])
        first_name = self.escape_vcard_value(details['staff_cname'] + (' ' + ' '.join(details['staff_ename'].split(',')[1:]).strip() if ',' in details['staff_ename'] else ''))

        vcard = f"""BEGIN:VCARD
VERSION:3.0
N:{last_name};{first_name};;
ORG:{self.escape_vcard_value(details['company_name'])}
"""
        if details['title']:
            titles = [title.strip() for title in details['title'].split(';') if title.strip()]
            for title in titles:
                vcard += f"TITLE:{self.escape_vcard_value(title)}\n"
        if details['email']:
            vcard += f"EMAIL;TYPE=WORK:{self.escape_vcard_value(details['email'])}\n"
        if details['office_phone_no']:
            vcard += f"TEL;TYPE=WORK:{self.escape_vcard_value(details['office_phone_no'])}\n"
        if details['mobile_phone_no']:
            vcard += f"TEL;TYPE=CELL:{self.escape_vcard_value(details['mobile_phone_no'])}\n"
        if details['mobile_phone_no1']:
            vcard += f"TEL;TYPE=CELL:{self.escape_vcard_value(details['mobile_phone_no1'])}\n"
        if details['website']:
            vcard += f"URL:{self.escape_vcard_value(details['website'])}\n"
        vcard += "END:VCARD"
        return vcard

    def save_to_database(self, details, qr_bytes):
        """Save name card details and QR code to the database."""
        try:
            with self.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM dbo.name_card WHERE card_id = ?", (details['card_id'],))
                    exists = cursor.fetchone()[0] > 0
                    
                    if not exists:
                        card_sql = """
                            INSERT INTO dbo.name_card (card_id, staff_cname, staff_ename, company_name, title, email, 
                                                    office_phone_no, mobile_phone_no, mobile_phone_no1, website, qr_code, create_date, modify_date, modify_user, print_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), GETDATE(), ?, ?)
                        """
                        card_values = (
                            details['card_id'], details['staff_cname'], details['staff_ename'],
                            details['company_name'], details['title'], details['email'],
                            details['office_phone_no'], details['mobile_phone_no'], details['mobile_phone_no1'], details['website'], qr_bytes,
                            current_user.id, details['print_date'] if 'print_date' in details else None
                        )
                        cursor.execute(card_sql, card_values)
                        conn.commit()
        except pyodbc.Error as err:
            raise Exception(f"Database Error: {err}")

manager = NameCardManager()

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login with form validation and bcrypt password verification."""
    if request.method == 'POST':
        userid = request.form['userid']
        password = request.form['password'].encode('utf-8')
        try:
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT userid, username, password_hash, role FROM dbo.name_card_admin WHERE userid = ?", (userid,))
                    user = cursor.fetchone()
                    if user and bcrypt.checkpw(password, user[2].encode('utf-8')):
                        user_obj = User(user[0], user[1], user[3])
                        login_user(user_obj, remember=True)
                        session.permanent = True
                        return redirect(url_for('index'))
                    else:
                        flash('Invalid credentials', 'error')
        except pyodbc.Error as e:
            flash(f"Login error: {e}", 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Log out the current user and clear session."""
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/keep-alive', methods=['POST'])
@login_required
def keep_alive():
    """Keep user session alive via AJAX request."""
    return {'status': 'success'}, 200

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Handle name card creation and QR code generation."""
    qr_download_url = None
    form_details = {}

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'confirm_create':
            details = {
                'card_id': request.form['card_id'],
                'staff_cname': request.form['staff_cname'],
                'staff_ename': request.form['staff_ename'],
                'company_name': request.form['company_name'],
                'title': request.form['title'],
                'email': request.form['email'],
                'office_phone_no': request.form['office_phone_no'],
                'mobile_phone_no': request.form['mobile_phone_no'],
                'mobile_phone_no1': request.form['mobile_phone_no1'],
                'website': request.form['website'],
                'print_date': request.form['print_date'] if request.form['print_date'] else None
            }
        else:
            current_date = datetime.now().strftime('%Y%m%d')
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""SELECT COUNT(*) FROM dbo.name_card WHERE card_id LIKE ?""", (f"{current_date}-%",))
                    result = cursor.fetchone()
                    count = int(result[0]) if result and result[0] is not None else 0
                    serial = str(count + 1).zfill(3)
                    card_id = f"{current_date}-{serial}"

            details = {
                'card_id': card_id,
                'staff_cname': request.form['staff_cname'],
                'staff_ename': request.form['staff_ename'],
                'company_name': request.form['company_name'],
                'title': request.form['title'],
                'email': request.form['email'],
                'office_phone_no': request.form['office_phone_no'],
                'mobile_phone_no': request.form['mobile_phone_no'],
                'mobile_phone_no1': request.form['mobile_phone_no1'],
                'website': request.form['website'],
                'print_date': request.form['print_date'] if request.form['print_date'] else None
            }

            # Validate required fields
            required_fields = ['staff_ename', 'email']
            for field in required_fields:
                if not details[field]:
                    flash(f'{field.replace("_", " ").title()} is required!', 'error')
                    return render_template('index.html', qr_download_url=qr_download_url, form_details=details)

            # Check for duplicate email
            try:
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*) FROM dbo.name_card WHERE email = ?", (details['email'],))
                        email_exists = cursor.fetchone()[0] > 0

                if email_exists:
                    flash('This email already exists in the database!', 'warning')
                    return render_template('index.html', qr_download_url=qr_download_url, show_warning=True, form_details=details)

            except pyodbc.Error as err:
                flash(f"Error checking email: {err}", 'error')
                return render_template('index.html', qr_download_url=qr_download_url, form_details=details)
            
        try:
            # Generate vCard and QR code
            qr_data = manager.generate_vcard(details)
            
            # Check if logo file exists
            if not os.path.exists(manager.logo_path):
                flash(f"Company logo not found at {manager.logo_path}", 'error')
                return render_template('index.html', qr_download_url=qr_download_url, form_details=details)
            
            qr_image = manager.generate_qr_code(qr_data)
            qr_filename = f"name_card_{details['card_id']}.png"
            qr_path = os.path.join(manager.upload_folder, qr_filename)
            
            # Save QR code with error handling
            try:
                qr_image.save(qr_path, dpi=(300, 300))
            except Exception as e:
                flash(f"Error saving QR code: {e}", 'error')
                return render_template('index.html', qr_download_url=qr_download_url, form_details=details)
            
            with open(qr_path, 'rb') as f:
                qr_bytes = f.read()
            
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM dbo.name_card WHERE card_id = ?", (details['card_id'],))
                    exists = cursor.fetchone()[0] > 0
            
            if not exists:
                manager.save_to_database(details, qr_bytes)
            else:
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        update_sql = """
                            UPDATE dbo.name_card
                            SET staff_cname = ?, staff_ename = ?, company_name = ?, title = ?, email = ?, 
                                office_phone_no = ?, mobile_phone_no = ?, mobile_phone_no1 = ?, website = ?, qr_code = ?, 
                                modify_date = GETDATE(), modify_user = ?, print_date = ?
                            WHERE card_id = ?
                        """
                        cursor.execute(update_sql, (
                            details['staff_cname'], details['staff_ename'], details['company_name'],
                            details['title'], details['email'], details['office_phone_no'],
                            details['mobile_phone_no'], details['mobile_phone_no1'], details['website'], qr_bytes, current_user.id, 
                            details['print_date'] if 'print_date' in details else None, details['card_id']
                        ))
                        conn.commit()
            
            flash(f'QR Code has been created! Card ID: {details["card_id"]}', 'success')
            qr_download_url = url_for('static', filename=f'qr_codes/{qr_filename}')
            return render_template('index.html', qr_download_url=qr_download_url)
            
        except Exception as e:
            flash(f"Error: {str(e)}", 'error')
            return render_template('index.html', qr_download_url=qr_download_url, form_details=details)
    
    return render_template('index.html', qr_download_url=qr_download_url)

@app.route('/add_admin', methods=['GET', 'POST'])
@login_required
def add_admin():
    if current_user.role != 'admin':
        flash('您無權新增管理員！', 'error')
        return redirect(url_for('index'))
    if request.method == 'POST':
        userid = request.form['userid']
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form['role']
        if password != confirm_password:
            flash('密碼與確認密碼不一致！', 'error')
            return render_template('add_admin.html')
        try:
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM dbo.name_card_admin WHERE userid = ?", (userid,))
                    if cursor.fetchone()[0] > 0:
                        flash('用戶 ID 已存在！', 'error')
                        return render_template('add_admin.html')
                    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    admin_sql = """
                        INSERT INTO dbo.name_card_admin (userid, username, create_date, modify_date, modify_user, password_hash, role)
                        VALUES (?, ?, GETDATE(), GETDATE(), ?, ?, ?)
                    """
                    cursor.execute(admin_sql, (userid, username, current_user.id, hashed_password, role))
                    conn.commit()
                    flash(f"管理員 '{userid}' 新增成功！", 'success')
                    return redirect(url_for('index'))
        except pyodbc.Error as err:
            flash(f"新增管理員失敗：{err}", 'error')
    return render_template('add_admin.html')

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow users to change their password."""
    if request.method == 'POST':
        current_password = request.form['current_password'].encode('utf-8')
        new_password = request.form['new_password'].encode('utf-8')
        try:
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT password_hash FROM dbo.name_card_admin WHERE userid = ?", (current_user.id,))
                    user = cursor.fetchone()
                    if user and bcrypt.checkpw(current_password, user[0].encode('utf-8')):
                        hashed_new_password = bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')
                        cursor.execute(
                            "UPDATE dbo.name_card_admin SET password_hash = ?, modify_date = GETDATE(), modify_user = ? WHERE userid = ?",
                            (hashed_new_password, current_user.id, current_user.id)
                        )
                        conn.commit()
                        flash('Password changed successfully!', 'success')
                        return redirect(url_for('index'))
                    else:
                        flash('Current password is incorrect!', 'error')
        except pyodbc.Error as err:
            flash(f"Error changing password: {err}", 'error')
    return render_template('change_password.html')

@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    """Allow admin users to manage other users (change password, role, or delete)."""
    if current_user.role != 'admin':
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form['action']
        target_userid = request.form['userid']
        
        try:
            with manager.connect_db() as conn:
                with conn.cursor() as cursor:
                    if action == 'change_password':
                        new_password = request.form['new_password'].encode('utf-8')
                        hashed_new_password = bcrypt.hashpw(new_password, bcrypt.gensalt()).decode('utf-8')
                        cursor.execute(
                            "UPDATE dbo.name_card_admin SET password_hash = ?, modify_date = GETDATE(), modify_user = ? WHERE userid = ?",
                            (hashed_new_password, current_user.id, target_userid)
                        )
                        conn.commit()
                        flash(f"Password for '{target_userid}' changed successfully!", 'success')
                    
                    elif action == 'delete':
                        cursor.execute("DELETE FROM dbo.name_card_admin WHERE userid = ?", (target_userid,))
                        conn.commit()
                        flash(f"User '{target_userid}' deleted successfully!", 'success')
                    
                    elif action == 'change_role':
                        new_role = request.form['new_role']
                        cursor.execute(
                            "UPDATE dbo.name_card_admin SET role = ?, modify_date = GETDATE(), modify_user = ? WHERE userid = ?",
                            (new_role, current_user.id, target_userid)
                        )
                        conn.commit()
                        flash(f"Role for '{target_userid}' changed to '{new_role}' successfully!", 'success')
        
        except pyodbc.Error as err:
            flash(f"Error managing user: {err}", 'error')
    
    try:
        with manager.connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT userid, username, role FROM dbo.name_card_admin")
                users = cursor.fetchall()
    except pyodbc.Error as err:
        flash(f"Error fetching users: {err}", 'error')
        users = []
    
    return render_template('manage_users.html', users=users)

@app.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    """Handle name card search, update, and copy operations."""
    results = []
    search_term = session.get('search_term', '')

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update':
            try:
                details = {
                    'card_id': request.form['card_id'],
                    'staff_cname': request.form['staff_cname'],
                    'staff_ename': request.form['staff_ename'],
                    'company_name': request.form['company_name'],
                    'title': request.form['title'],
                    'email': request.form['email'],
                    'office_phone_no': request.form['office_phone_no'],
                    'mobile_phone_no': request.form['mobile_phone_no'],
                    'mobile_phone_no1': request.form['mobile_phone_no1'],
                    'website': request.form['website'],
                    'print_date': request.form['print_date'] if request.form['print_date'] else None
                }
                
                qr_data = manager.generate_vcard(details)
                
                if not os.path.exists(manager.logo_path):
                    flash(f"Company logo not found at {manager.logo_path}", 'error')
                    return render_template('search.html', results=results)
                
                qr_image = manager.generate_qr_code(qr_data)
                qr_filename = f"name_card_{details['card_id']}.png"
                qr_path = os.path.join(manager.upload_folder, qr_filename)
                
                try:
                    qr_image.save(qr_path, dpi=(300, 300))
                except Exception as e:
                    flash(f"Error saving QR code: {e}", 'error')
                    return render_template('search.html', results=results)
                
                with open(qr_path, 'rb') as f:
                    qr_bytes = f.read()
                
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        update_sql = """
                            UPDATE dbo.name_card
                            SET staff_cname = ?, staff_ename = ?, company_name = ?, title = ?, email = ?, 
                                office_phone_no = ?, mobile_phone_no = ?, mobile_phone_no1 = ?, website = ?, qr_code = ?, 
                                modify_date = GETDATE(), modify_user = ?, print_date = ?
                            WHERE card_id = ?
                        """
                        cursor.execute(update_sql, (
                            details['staff_cname'], details['staff_ename'], details['company_name'],
                            details['title'], details['email'], details['office_phone_no'],
                            details['mobile_phone_no'], details['mobile_phone_no1'], details['website'], qr_bytes, current_user.id, 
                            details['print_date'] if 'print_date' in details else None, details['card_id']
                        ))
                        conn.commit()
                        flash('Record updated successfully!', 'success')
                
                search_term = session.get('search_term', '')
                search_term_like = f'%{search_term}%'
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT card_id, staff_cname, staff_ename, company_name, title, email, 
                                   office_phone_no, mobile_phone_no, mobile_phone_no1, website, qr_code, print_date 
                            FROM dbo.name_card 
                            WHERE card_id LIKE ? 
                               OR staff_cname LIKE ? 
                               OR staff_ename LIKE ?
                        """, (search_term_like, search_term_like, search_term_like))
                        results = cursor.fetchall()
                        if not results:
                            flash('No records found for this search term.', 'error')
                        else:
                            for i, row in enumerate(results):
                                qr_filename = f"name_card_{row[0]}.png"
                                qr_path = os.path.join(manager.upload_folder, qr_filename)
                                try:
                                    with open(qr_path, 'wb') as f:
                                        f.write(row[10])
                                except Exception as e:
                                    flash(f"Error saving QR code for result: {e}", 'error')
                                results[i] = row[:10] + (qr_filename,) + (row[11],)
                return render_template('search.html', results=results)

            except pyodbc.Error as err:
                flash(f"Error updating record: {err}", 'error')
                return render_template('search.html', results=results)
        
        elif action == 'copy':
            try:
                card_id_to_copy = request.form['card_id_to_copy']
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT staff_cname, staff_ename, company_name, title, email, 
                                   office_phone_no, mobile_phone_no, mobile_phone_no1, website, print_date 
                            FROM dbo.name_card 
                            WHERE card_id = ?
                        """, (card_id_to_copy,))
                        record = cursor.fetchone()
                        if not record:
                            flash('Record not found!', 'error')
                            return render_template('search.html', results=results)

                current_date = datetime.now().strftime('%Y%m%d')
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT COUNT(*) 
                            FROM dbo.name_card 
                            WHERE card_id LIKE ?
                        """, (f"{current_date}-%",))
                        result = cursor.fetchone()
                        count = int(result[0]) if result and result[0] is not None else 0
                        serial = str(count + 1).zfill(3)
                        new_card_id = f"{current_date}-{serial}"
                        
                details = {
                    'card_id': new_card_id,
                    'staff_cname': record[0] if record[0] else '',
                    'staff_ename': record[1] if record[1] else '',
                    'company_name': record[2] if record[2] else '',
                    'title': record[3] if record[3] else '',
                    'email': record[4] if record[4] else '',
                    'office_phone_no': record[5] if record[5] else '',
                    'mobile_phone_no': record[6] if record[6] else '',
                    'mobile_phone_no1': record[7] if record[7] else '',
                    'website': record[8] if record[8] else '',
                    'print_date': None
                }

                qr_data = manager.generate_vcard(details)
                
                if not os.path.exists(manager.logo_path):
                    flash(f"Company logo not found at {manager.logo_path}", 'error')
                    return render_template('search.html', results=results)
                
                qr_image = manager.generate_qr_code(qr_data)
                qr_filename = f"name_card_{new_card_id}.png"
                qr_path = os.path.join(manager.upload_folder, qr_filename)
                
                try:
                    qr_image.save(qr_path, dpi=(300, 300))
                except Exception as e:
                    flash(f"Error saving QR code: {e}", 'error')
                    return render_template('search.html', results=results)
                
                with open(qr_path, 'rb') as f:
                    qr_bytes = f.read()
                
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        insert_sql = """
                            INSERT INTO dbo.name_card (card_id, staff_cname, staff_ename, company_name, title, email, 
                                                       office_phone_no, mobile_phone_no, mobile_phone_no1, website, qr_code, create_date, modify_date, modify_user, print_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), GETDATE(), ?, ?)
                        """
                        cursor.execute(insert_sql, (
                            new_card_id, details['staff_cname'], details['staff_ename'], details['company_name'],
                            details['title'], details['email'], details['office_phone_no'], details['mobile_phone_no'], details['mobile_phone_no1'],
                            details['website'], qr_bytes, current_user.id, details['print_date'] if 'print_date' in details else None
                        ))
                        conn.commit()
                        flash(f'Record copied successfully! New Card ID: {new_card_id}', 'success')
                
                search_term = session.get('search_term', '')
                search_term_like = f'%{search_term}%'
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT card_id, staff_cname, staff_ename, company_name, title, email, 
                                   office_phone_no, mobile_phone_no, mobile_phone_no1, website, qr_code, print_date 
                            FROM dbo.name_card 
                            WHERE card_id LIKE ? 
                               OR staff_cname LIKE ? 
                               OR staff_ename LIKE ?
                        """, (search_term_like, search_term_like, search_term_like))
                        results = cursor.fetchall()
                        if not results:
                            flash('No records found for this search term.', 'error')
                        else:
                            for i, row in enumerate(results):
                                qr_filename = f"name_card_{row[0]}.png"
                                qr_path = os.path.join(manager.upload_folder, qr_filename)
                                try:
                                    with open(qr_path, 'wb') as f:
                                        f.write(row[10])
                                except Exception as e:
                                    flash(f"Error saving QR code for result: {e}", 'error')
                                results[i] = row[:10] + (qr_filename,) + (row[11],)
                return render_template('search.html', results=results)

            except pyodbc.Error as err:
                flash(f"Error copying record: {err}", 'error')
                return render_template('search.html', results=results)
            except Exception as e:
                flash(f"Error: {str(e)}", 'error')
                return render_template('search.html', results=results)

        else:
            try:
                search_term = request.form['search_term']
                session['search_term'] = search_term
            except KeyError:
                flash('Search term is required!', 'error')
                return render_template('search.html', results=results)
            
            try:
                with manager.connect_db() as conn:
                    with conn.cursor() as cursor:
                        search_term_like = f'%{search_term}%'
                        cursor.execute("""
                            SELECT card_id, staff_cname, staff_ename, company_name, title, email, 
                                   office_phone_no, mobile_phone_no, mobile_phone_no1, website, qr_code, print_date 
                            FROM dbo.name_card 
                            WHERE card_id LIKE ? 
                               OR staff_cname LIKE ? 
                               OR staff_ename LIKE ?
                        """, (search_term_like, search_term_like, search_term_like))
                        results = cursor.fetchall()
                        if not results:
                            flash('No records found for this search term.', 'error')
                        else:
                            for i, row in enumerate(results):
                                qr_filename = f"name_card_{row[0]}.png"
                                results[i] = row[:10] + (qr_filename,) + (row[11],)
            except pyodbc.Error as err:
                flash(f"Error searching records: {err}", 'error')
    
    return render_template('search.html', results=results)

if __name__ == '__main__':
    # Run the application in development mode
    # WARNING: Do not use debug=True in production to avoid exposing sensitive information
    app.run(debug=True, host='0.0.0.0', port=5000)