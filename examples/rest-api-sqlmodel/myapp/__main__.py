from werkzeug import run_simple

from myapp import app

if __name__ == '__main__':
    run_simple('localhost', 8000, app.wsgi())
