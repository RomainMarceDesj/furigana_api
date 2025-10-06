import os
from flask import Flask, request, jsonify
from sudachipy import dictionary, tokenizer
import re
import json
from flask_cors import CORS, cross_origin
from PyPDF2 import PdfReader
import docx
import sqlite3
import pytesseract
from PIL import Image
import io
from pdf2image import convert_from_bytes
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

base_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(base_dir, '..', '..'))

# --- NEW DATABASE CONFIGURATION FOR USERS ---
user_db_path = os.path.join(base_dir, 'users.db') 
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{user_db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 
app.secret_key = 'YOUR_VERY_SECRET_KEY_HERE' # REQUIRED for sessions/LoginManager

db = SQLAlchemy(app) # Initialize SQLAlchemy with your Flask app

# --- LOGIN MANAGER SETUP ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # Store the password as a secure hash, NOT plain text!
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True) # Optional field
    
    # Method to hash a password
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Method to check a password
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# This function is crucial for Flask-Login to load the user from the session ID
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

db_path = os.path.join(base_dir, 'jmdict.db')
tokenizer_obj = dictionary.Dictionary().create()
mode = tokenizer.Tokenizer.SplitMode.C
try:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    print("Connected to jmdict.db successfully.")
except sqlite3.OperationalError:
    print("Error: jmdict.db not found. Please run create_db_from_json.py first.")
    conn = None

mode = tokenizer.Tokenizer.SplitMode.C


#helper functions 


def kata_to_hira(katakana):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in katakana
    )

def lookup_translation(lemma, reading_hira):
    if conn is None:
        return ""
    
    cursor = conn.cursor()
    query = "SELECT translations FROM words WHERE kanji_form = ? OR kana_form = ?"
    cursor.execute(query, (lemma, reading_hira))
    result = cursor.fetchone()
    if result:
        translations = result[0].split(' | ')
        # ⬇️ Limiting to the first two translations
        limited_translations = translations[:2]
        return " | ".join(limited_translations)
    return ""


def lookup_kanji_data(kanji_char):
    """
    Looks up the JLPT level, Mainichi Shinbun frequency, and school grade for a single kanji.
    Returns a dictionary or None if not found.
    """
    if conn is None:
        return None
    
    cursor = conn.cursor()
    query = "SELECT jlpt_level, freq_mainichi_shinbun, grade FROM kanji_jlpt WHERE kanji = ?"
    cursor.execute(query, (kanji_char,))
    result = cursor.fetchone()
    
    if result:
        # Return a dictionary with the fetched data
        return {
            "kanji": kanji_char,
            "jlpt_level": result[0],
            "freq_mainichi_shinbun": result[1],
            "grade": result[2]
        }
    return None

def read_txt(file_content):
    encodings_to_try = ['utf-8', 'cp932', 'shift_jis', 'euc-jp']
    for encoding in encodings_to_try:
        try:
            return file_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Failed to decode text file with common encodings.")

def read_pdf(file_stream):
    try:
        pdf_reader = PdfReader(file_stream)
        text_content = ""
        for page in pdf_reader.pages:
            text_content += page.extract_text()
        return text_content
    except Exception as e:
        raise ValueError(f"Error reading PDF: {e}")

def read_docx(file_stream):
    try:
        doc = docx.Document(file_stream)
        text_content = ""
        for para in doc.paragraphs:
            text_content += para.text + "\n"
        return text_content
    except Exception as e:
        raise ValueError(f"Error reading DOCX: {e}")

def read_image_with_ocr(file_stream):
    try:
        print("Starting image OCR processing...")
        img = Image.open(io.BytesIO(file_stream.read()))
        print(f"Image opened successfully: {img.format}, {img.size}")
        # Use Tesseract to get the text, specifying Japanese language
        text = pytesseract.image_to_string(img, lang='jpn')
        print(f"OCR completed, text length: {len(text)}")
        return text
    except Exception as e:
        print(f"An error occurred during image OCR: {e}")
        return None
    
def read_pdf_with_ocr(file_stream):
    try:
        # Convert PDF pages to a list of images
        images = convert_from_bytes(file_stream.read())
        extracted_text = ""
        for image in images :
            # Use Tesseract on each image from the PDF
            text = pytesseract.image_to_string(image, lang='jpn')
            extracted_text += text + "\n"
        return extracted_text
    except Exception as e:
        print(f"Error converting PDF to image for OCR: {e}")
        return None

def process_text_data(text_content, start_position, page_size):
    total_length = len(text_content)
    page_text = text_content[start_position:start_position + page_size]

    if not page_text:
        return {"data": [], "totalLength": 0}

    paragraphs = page_text.split("。")
    output = []
    id_counter = 1

    for para in paragraphs:
        if not para.strip():
            continue
        para_output = []
        for morpheme in tokenizer_obj.tokenize(para, mode):
            surface = morpheme.surface()
            reading_kata = morpheme.reading_form()
            reading_hira = kata_to_hira(reading_kata)
            lemma = morpheme.dictionary_form()

            kanji_info_list = []
            is_kanji_word = False
            for char in surface:
                if re.match(r'[\u4E00-\u9FFF]', char):
                    is_kanji_word = True
                    # Call the new lookup function
                    kanji_data = lookup_kanji_data(char)
                    if kanji_data:
                        kanji_info_list.append(kanji_data)

            if is_kanji_word:
                translation = lookup_translation(lemma, reading_hira)
                
                para_output.append({
                    "type": "word",
                    "kanji": surface,
                    "furigana": reading_hira,
                    "translation": translation,
                    "id": id_counter,
                    "showFurigana": False,
                    "showTranslation": False,
                    "kanji_levels": kanji_info_list # The list now contains full kanji data
                })
                id_counter += 1
            else:
                para_output.append({
                    "type": "text",
                    "value": surface
                })
        output.append(para_output)

    return {"data": output, "totalLength": total_length}

@app.route('/ocr', methods=['POST'])
@cross_origin()
def ocr():
    print("=== OCR REQUEST DEBUG ===")
    print("Headers:", dict(request.headers))
    print("request.files:", request.files)
    print("request.form:", request.form)
    
    # Debug: Check all available file keys
    print("Available file keys:", list(request.files.keys()))
    
    # Check content type
    print("Content-Type:", request.headers.get('Content-Type'))
    
    # Check if any image file key is in the request (be more flexible)
    image_file = None
    if 'image_file' in request.files:
        image_file = request.files['image_file']
        print("Found image_file in request.files")
    elif 'file' in request.files:
        image_file = request.files['file']
        print("Found file in request.files")
    else:
        print("No image file found in request")
        return jsonify({"error": "No image file found in request. Expected 'image_file' or 'file'"}), 400

    if image_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = image_file.filename
    file_ext = os.path.splitext(filename)[1].lower()
    print(f"Processing file: {filename}, extension: {file_ext}")
    
    file_stream = io.BytesIO(image_file.read())
    
    start_position = int(request.form.get("start_position", 0))
    page_size = int(request.form.get("page_size", 1000))
    print(f"Start position: {start_position}, Page size: {page_size}")
    
    try:
        if file_ext in ['.jpg', '.jpeg', '.png']:
            print(f"Processing image file with extension: {file_ext}")
            text_content = read_image_with_ocr(file_stream)
        elif file_ext == '.pdf':
            print("Processing PDF file with OCR")
            text_content = read_pdf_with_ocr(file_stream)
        else:
            return jsonify({"error": f"File type '{file_ext}' is not supported for this endpoint."}), 415

        print(f"Extracted text content length: {len(text_content) if text_content else 0}")
        
        if not text_content:
            return jsonify({"error": "Could not extract text from the file."}), 400
    
        # Call process_text_data and then jsonify the result
        print("Processing text data...")
        result = process_text_data(text_content, start_position, page_size)
        print(f"Text processing completed, result data length: {len(result.get('data', []))}")
        return jsonify(result)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        return jsonify({"error": f"An unexpected error occurred with the uploaded file: {str(e)}"}), 500

@app.route('/register', methods=['POST'])
@cross_origin()
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    with app.app_context():
        # Check if user already exists
        if db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none():
            return jsonify({"error": "User already exists"}), 409

        # Create new user and hash the password
        new_user = User(username=username)
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()

    return jsonify({"message": "Registration successful"}), 201

@app.route('/login', methods=['POST'])
@cross_origin()
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    with app.app_context():
        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

        if user is None or not user.check_password(password):
            return jsonify({"error": "Invalid username or password"}), 401

        # The core Flask-Login call: sets the user as logged in for the session
        login_user(user) 
    
    # You can return user details if needed, but for security, keep it minimal
    return jsonify({"message": "Login successful", "username": user.username}), 200

@app.route("/analyze", methods=["POST"])
@cross_origin() # Add this line
def analyze_text():
    
    """
    Analyzes an uploaded document or a pre-selected book.
    It reads the file content, extracts text, and then tokenizes it.
    """
    
    # ----------------------------------------------------
    # Part 1: Handle File Uploads (from a form-data request)
    # ----------------------------------------------------
    # Check if a file was uploaded with the request
    print("Headers:", dict(request.headers))
    print("request.files:", request.files)
    print("request.form:", request.form)
    if 'file' in request.files and request.files['file'].filename != '':
        try:
            file = request.files['file']
            file_content_binary = file.read()
            # Create a file-like object in memory. This allows us to read the content multiple times if needed.
            file_stream = io.BytesIO(file_content_binary)
            
            file_ext = os.path.splitext(file.filename)[1].lower()
            start_position = int(request.form.get("start_position", 0))
            page_size = int(request.form.get("page_size", 1000))
            
            # Use a clear if/elif structure to handle each file type.
            if file_ext == '.txt':
                decoded_text = read_txt(file_content_binary)
            
            elif file_ext == '.pdf':
                decoded_text = read_pdf(file_stream)
                # If no text is found in the PDF, try OCR as a fallback.
                if not decoded_text:
                    file_stream.seek(0) # Rewind the stream to the beginning for the OCR function.
                    decoded_text = read_pdf_with_ocr(file_stream)
                    if not decoded_text:
                        # If OCR also fails, return a specific error.
                        return jsonify({"error": "The PDF has no readable content and OCR failed."}), 400
            
            elif file_ext in ['.docx', '.doc']:
                decoded_text = read_docx(file_stream)
            
            else:
                # If the file type is not supported, return an error.
                return jsonify({"error": f"File type '{file_ext}' is not supported."}), 415

            # If everything is successful, process the text and return the result.
            return jsonify(process_text_data(decoded_text, start_position, page_size))
        
        except Exception as e:
            # Catch any unexpected errors during file processing and return a 500 status.
            return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

    # ----------------------------------------------------
    # Part 2: Handle Pre-selected Books (from a JSON request)
    # ----------------------------------------------------
    # This block of code runs if a file was NOT uploaded.
    data = request.get_json()
    filepath = data.get("filepath")
    start_position = int(data.get("start_position", 0))
    page_size = int(data.get("page_size", 1000))

    if filepath:
        file_path = os.path.join(base_dir, 'public', filepath)
        try:
            # Read the content of the selected book.
            with open(file_path, 'rb') as f:
                file_content_binary = f.read()
                decoded_text = read_txt(file_content_binary)
            
            return jsonify(process_text_data(decoded_text, start_position, page_size))
        
        except FileNotFoundError:
            return jsonify({"error": "Book not found."}), 404
        except Exception as e:
            return jsonify({"error": f"An error occurred with the book: {e}"}), 500
            
    # If no file was uploaded and no book was selected, return an empty response.
    return jsonify({"data": [], "totalLength": 0})

@app.route('/warmup', methods=['GET'])
@cross_origin()
def warmup():
    return jsonify({"status": "warmup successful"})

@app.route('/logout')
@cross_origin()
@login_required # Ensures only logged-in users can access this
def logout():
    logout_user()
    return jsonify({"message": "Logout successful"}), 200

@app.route('/health', methods=['GET'])
@cross_origin()
def health_check():
    """Health check endpoint for Railway deployment monitoring"""
    try:
        # Verificar que la base de datos esté accesible
        if conn is None:
            return jsonify({"status": "unhealthy", "error": "Database connection failed"}), 503
        
        # Verificar que Tesseract esté disponible
        try:
            import pytesseract
            # Intentar un OCR simple de prueba
            test_result = pytesseract.get_tesseract_version()
        except Exception as e:
            return jsonify({"status": "unhealthy", "error": f"Tesseract OCR not available: {str(e)}"}), 503
        
        return jsonify({
            "status": "healthy",
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "database": "connected",
            "tesseract": "available"
        }), 200
        
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
else:
    print("hello")
