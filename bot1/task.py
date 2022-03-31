from core import setup, navigate, get_news_info, logger


def main():
    try:
        setup()
        navigate()
        get_news_info()
    except Exception as e:
        logger.error(f'{e} \n Bot execution failed')
        raise e


if __name__ == '__main__':
    main()
