from flask import Flask

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'tracker2026sapo'
    app.config['UPLOAD_FOLDER'] = '/Data2/track/uploads'
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
    app.config['APPLICATION_ROOT'] = '/track'

    from app.routes import main
    app.register_blueprint(main)

    return app
# test
