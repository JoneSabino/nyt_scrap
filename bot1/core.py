import re
import datetime
from dateutil.relativedelta import relativedelta
from RPA.Browser.Playwright import Playwright
from RPA.Robocorp.WorkItems import WorkItems
from RPA.Excel.Files import Files
from RPA.FileSystem import FileSystem
from Browser import ElementState, SelectAttribute
from typing import Dict, Union
from loguru import logger

wb_path = r'./output/news.xlsx'

pl = Playwright()
wi = WorkItems()
excel = Files()
fs = FileSystem()


def setup():
    """
    Setup the bot.
    """
    logger.info('Setting up the bot')
    wi.get_input_work_item()
    excel.create_workbook(wb_path)
    excel.rename_worksheet('Sheet', 'News')
    excel.save_workbook()
    pl.new_browser(
        headless=True,
    )
    pl.new_context(acceptDownloads=True)


def navigate():
    """
    Navigate the bot.
    1. Open the site by following the link
    2. Enter a phrase in the search field
    3. On the result page, apply the following filters:
        - select a news category or section
        - choose the latest news
    """
    section = wi.get_work_item_variable('news_section')
    search_phrase = wi.get_work_item_variable('search_phrase')

    # home page
    accept_cookies = 'button[data-testid="GDPR-accept"]'
    search_icon = 'button[data-test-id="search-button"]'
    search_field = 'input[data-testid="search-input"]'
    go_button = 'button[data-test-id="search-submit"]'

    # search results page
    section_button = '//label[contains(text(), "Section")]'
    sort_button = 'select[data-testid$="sortBy"]'
    date_range_button = 'button[data-testid^="search-date"]'
    spec_date_opt = 'button[value="Specific Dates"]'
    start_date_field = 'input[aria-label="start date"]'
    end_date_field = 'input[aria-label="end date"]'
    section_option = f'button[aria-label="{section}"]'
    alt_section_option = f'input[value^="{section}"]'
    show_more_button = 'button[data-testid*="show-more"]'

    # Open the site by following the link
    pl.set_browser_timeout(30)
    logger.info('Opening https://nytimes.com')
    pl.new_page('https://nytimes.com')
    pl.set_browser_timeout(10)

    # Enter a phrase in the search field
    pl.click(search_icon)
    pl.wait_for_elements_state(search_field, ElementState(4), timeout=10)
    pl.type_text(search_field, search_phrase)
    logger.info(f'Searching for {search_phrase} news')
    pl.click(go_button)

    # select a news category or section
    pl.click(section_button)
    try:
        pl.set_browser_timeout(1)
        pl.click(section_option)
    except AssertionError:
        pl.check_checkbox(alt_section_option)
    pl.set_browser_timeout(10)

    # remove the GDPR banner
    pl.click(accept_cookies)

    # input the date range
    pl.click(date_range_button)
    pl.click(spec_date_opt)
    date_range = _set_date_range()
    pl.fill_text(start_date_field, date_range['start'])
    pl.fill_text(end_date_field, date_range['end'])
    pl.click('#searchTextField')

    # choose the latest news
    pl.select_options_by(sort_button, SelectAttribute['value'], 'newest')

    # load all news
    pl.set_browser_timeout(4)
    while True:
        try:
            pl.wait_for_elements_state(show_more_button, ElementState(16384), timeout=4)
            pl.click(show_more_button)
        except AssertionError:
            pl.set_browser_timeout(10)
            break

    pl.set_browser_timeout(10)


def get_news_info():
    """
    Get the relevant data from the news, and write it to the excel file.
    """
    search_phrase = wi.get_work_item_variable('search_phrase')

    # Selectors
    news_date = 'span.css-17ubb9w'
    news_title = 'h4'
    news_description = 'p.css-16nhkrn'
    search_result_items = 'div.css-1kl114x'
    data = {
        'Title': '',
        'Date': '',
        'Description': '',
        'Picture Filename': '',
        'Search Phrase Count': '',
        'Has Money': bool,
    }

    logger.info('Collecting news data')

    news_list = pl.get_elements(search_result_items)
    pl.set_browser_timeout(1)
    for news in news_list:
        data['Date'] = pl.get_attribute(f'{news} {news_date}', 'aria-label')
        data['Title'] = pl.get_text(f'{news} {news_title}')
        try:
            data['Description'] = pl.get_text(f'{news} {news_description}')
        except AssertionError:
            logger.info('No description in this news')
            data['Description'] = ''

        img_meta = _get_picture_metadata(news)

        data['Picture Filename'] = img_meta['filename']

        if img_meta['url']:
            _download_picture(img_meta['url'])

        data['Search Phrase Count'] = _count_search_phrase(
            data['Title'], data['Description'], search_phrase
        )
        data['Has Money'] = _money_exists(data['Title'], data['Description'])

        _write_to_excel(data, 'News')

    pl.set_browser_timeout(10)


def _set_date_range() -> Dict[str, str]:
    """Set the date range for the search

    Example of how this should work:
        - 0 or 1: only the current month,
        - 2: current and previous month,
        - 3: current and two previous months, and so on
    """
    today = datetime.datetime.today()
    months = int(wi.get_work_item_variable('months'))
    date_range = months - 1 if months > 0 else 0

    end_date = today.strftime('%m/%d/%Y')
    if date_range in [0, 1]:
        start_date = today.replace(day=1).strftime('%m/%d/%Y')
    else:
        date = today - relativedelta(months=date_range)
        start_date = date.strftime('%m/%d/%Y')
    logger.info(f'Searching news from {start_date} to {end_date}')
    return {'start': start_date, 'end': end_date}


def _count_search_phrase(title: str, description: str, search_phrase: str) -> str:
    """
    Count the number of search phrases
    """
    # Check if the search phrase is in the title or description
    tc = title.count(search_phrase)
    dc = description.count(search_phrase)
    logger.info(f'Number of times \'{search_phrase}\' was found in the: \n' 
                'title: {tc} \n description: {dc}')
    return str(dc + tc)


def _money_exists(title: str, description: str) -> bool:
    """Check if the title contains any amount of money"""
    money_pattern = re.compile(
        r'(\$\d+\,*\d*\.?\d*)|(\d+\sdollars|\d+\sUSD)', re.MULTILINE | re.IGNORECASE
    )

    title_money = money_pattern.findall(title)
    description_money = money_pattern.findall(description)
    logger.info(f'Money in title: {title_money} \n Money in description: {description_money}')
    return True if title_money or description_money else False


def _write_to_excel(data: Dict[str, Union[str, bool]], worksheet: str, workbook_path: str = wb_path):
    try:
        excel.open_workbook(workbook_path)
        excel.append_rows_to_worksheet(data, worksheet, header=True)
        excel.save_workbook(workbook_path)
        excel.close_workbook()
        logger.info('Excel: Row appended with success')
    except Exception as e:
        logger.error(
            f'{e} \n Failed when trying to generate \
            the excel file'
        )
        raise e


def _get_picture_metadata(news: str) -> Dict[str, str]:
    """Get the picture filename"""
    picture = 'img'

    try:
        srcset = pl.get_attribute(f'{news} {picture}', 'srcset')
        picture_url = srcset.split(' ')[0]
        pic_filename = picture_url.split('/')[-1]
        logger.info(f'Picture filename: {pic_filename}')
    except AssertionError:
        logger.warning('No picture in this news')
        pic_filename = ''
        picture_url = ''

    return {'filename': pic_filename, 'url': picture_url}


def _download_picture(picture_url: str):
    """Download the picture"""
    logger.info(f'Downloading picture: {picture_url}')
    img = pl.download(picture_url)
    file_extension = img['suggestedFilename'].split('.')[-1]
    fs.change_file_extension(f'{img["saveAs"]}', f'.{file_extension}')
    logger.info(f'Picture downloaded with success')
