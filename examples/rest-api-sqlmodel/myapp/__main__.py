from werkzeug import run_simple

from rolo.gateway.wsgi import WsgiGateway


def main():
    gateway = MyAppGateway()
    run_simple("localhost", 8000, WsgiGateway(gateway))


if __name__ == '__main__':
    main()
