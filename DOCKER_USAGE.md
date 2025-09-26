# Docker Setup for Furigana API

## Quick Start

1. **Build and run the application:**
   ```bash
   docker-compose up --build
   ```

2. **Access the application:**
   - API will be available at: http://localhost:5000
   - Health check: http://localhost:5000/health

## Available Services

### Development Mode (Default)
```bash
docker-compose up
```
- Runs the Flask application
- Exposes port 5000 directly

## Configuration

1. **Environment Variables:**
   - Copy `.env.example` to `.env` and modify as needed
   - Key settings: `FLASK_ENV`, `MAX_FILE_SIZE`, `LOG_LEVEL`

2. **File Upload Limits:**
   - Default: 50MB (configured in Flask app)
   - Modify application code if different limits needed

## Maintenance Commands

```bash
# View logs
docker-compose logs -f furigana-api

# Restart service
docker-compose restart furigana-api

# Update dependencies
docker-compose build --no-cache

# Stop all services
docker-compose down

# Remove volumes (careful - deletes data)
docker-compose down -v
```

## Database Files

The following files are mounted as read-only volumes:
- `jmdict.db` - Japanese dictionary database
- `jmdict_common_eng.json` - English translations
- `kanji_jlpt.json` - Kanji JLPT data

## Troubleshooting

1. **OCR not working:**
   - Ensure Tesseract Japanese language pack is installed
   - Check logs: `docker-compose logs furigana-api`

2. **File upload issues:**
   - Check file size limits in your Flask configuration
   - Verify upload directory permissions

3. **Health check failures:**
   - Application may still be starting
   - Increase `start_period` in docker-compose.yml if needed