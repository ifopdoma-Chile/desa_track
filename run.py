from app import create_app
from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response

app = create_app()
app.config['APPLICATION_ROOT'] = '/track'

app.wsgi_app = DispatcherMiddleware(
    Response('Not Found', status=404),
    {'/track': app.wsgi_app}
)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8102, debug=True)
