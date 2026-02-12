from bs4 import BeautifulSoup
import requests
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
from tqdm import tqdm

logging.basicConfig(level = logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Award:
  category: str
  winner: str
  nominees: List[str]

def clean_spaces(text: str) -> str:
  """
  Removes whitespace between quotation marks and parentheses when parsing.

  Ie. Parsing results in ( Brazil ), cleaned to (Brazil)
  """

  text = re.sub(r'"\s*([^"]*?)\s*"', r'"\1"', text)
  text = re.sub(r'\(\s*([^)]*?)\s*\)', r'(\1)', text)
  return text

def generate_oscar_urls(start_year: int = 1929, end_year: int = 2025) -> List[Dict]:
  """
  Generate URLs for every Oscar ceremony from start_year to end_year.
  """

  urls = []

  for year in range(start_year, end_year + 1):
    ceremony_num = year - 1928
    if 10 <= ceremony_num % 100 <= 13:
      suffix = "th"
    else:
      last_digit = ceremony_num % 10
      suffix = {
          1: "st",
          2: "nd",
          3: "rd"
      }.get(last_digit, "th")

    url = f"https://en.wikipedia.org/wiki/{ceremony_num}{suffix}_Academy_Awards"

    urls.append({
        "ceremony_number": ceremony_num,
        "year": year,
        "url": url,
    })

  return urls

class WikipediaScraper:
  """
  Scrapes data from Oscars Wikipedia pages.
  """

  # ! Awards table format is different for 18th (1946) - 49th (1977) awards. It uses separate cells for the awards/categories vs. it being in the same cell as the winners/nominees.
  # ? This issue doesn't appear to be a thing anymore after 10 months coming back to this (Feb 11, 2026)

  def __init__(self, url: str):
    self.url = url
    self.session = requests.Session()
    self.session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            "AppleWebKit/537.36 (KHTML, like Gecko)"
            "Chrome/134.0.0.0 Safari/537.36"
            )
    })
    self.soup = self.get_soup(self.url)

  def get_soup(self, url: str) -> BeautifulSoup:
    """
    Fetches and parses the HTML from the Wikipedia url.
    """

    try:
      response = self.session.get(url, allow_redirects = True)
      response.raise_for_status()
      return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
      logger.error(f"Failed to fetch {self.url}: {e}")
      raise

  def scrape_ceremony(self) -> Dict:
    """
    Scrape data from a single Oscar ceremony Wikipedia page.
    """

    logger.info(f"Scraping: {self.url}")

    ceremony_data = {
        "url": self.url,
        "date": self.get_date(),
        "awards": []
    }

    try:
      award_table_rows = self.get_award_table_rows()

      for row in award_table_rows[:]:
        cells = row.find_all("td")
        for cell in cells:
          award_data = Award(
              category = self.get_award(cell),
              winner = self.get_winner(cell),
              nominees = self.get_nominees(cell)
          )
          ceremony_data["awards"].append(award_data)

    except Exception as e:
      logger.error(f"Failed to parse ceremony {self.url}: {e}")

    return ceremony_data

  def get_award_table_rows(self) -> List[BeautifulSoup]:
    """
    Extracts the Awards table and its corresponding rows for subsequent parsing. This could be titled differently across different pages.
    """
    possible_titles = ["Awards", "Winners and nominees"]

    for header_tag in ["h3", "h2"]:
      for title in possible_titles:
        header = self.soup.find(header_tag, string = lambda s: s and s.lower().strip() == title.lower())
        if header:
          table = header.find_next("table", class_ = "wikitable")
          if table:
            return table.find_all("tr") # tr for rows.

    raise Exception("Awards section not found with expected headers.")

  def get_date(self) -> Optional[str]:
    """
    Extracts the year of the Academy Awards ceremony the Wikipedia infobox.
    """

    infobox = self.soup.find("table", class_ = "infobox vevent")
    if not infobox:
      return None

    for row in infobox.find_all("tr"):
      header = row.find("th") # th for header.
      if header and "Date" in header.text:
        date_cell = row.find("td")
        if date_cell:
          return date_cell.get_text(strip = True)

    return None

  def get_award(self, table_cell) -> str:
    """
    Extracts the award name from a table cell element. Returns "Unknown Award" if no award name is found.
    """

    award_div = table_cell.find("div")
    award_name = award_div.get_text(strip = True) if award_div else "Unknown Award"
    return award_name

  def split_nominee_text(self, nominee_text: str) -> Tuple[str, Optional[str]]:
    """
    Takes the nominee line item information and returns the primary winner and secondary information.

    Ie. In the 97th Oscars (2025):
    For Best Picture, Anora is the primary and Sean Baker (+ producers) is in the secondary.
    For Best Director, Sean Baker is the primary and Anora is the secondary.
    """

    if " – " in nominee_text:
      primary, secondary = nominee_text.split(" – ", 1)
    else:
      primary, secondary = nominee_text, None
    return [
        clean_spaces(primary.strip()),
        clean_spaces(secondary.strip()) if secondary else None
    ]

  def get_winner(self, table_cell) -> str:
    """
    Extracts the winner from the Wikipedia Awards table cells - usually bolded inside <ul><li>.
    """

    try:
      ul = table_cell.find("ul")
      main_li = ul.find("li")
      winner_text = main_li.find("b").get_text(separator = " ", strip = True)
      return self.split_nominee_text(winner_text)[0]
    except (AttributeError, TypeError):
      return "Unknown Winner"

  def get_nominees(self, table_cell) -> List[str]:
    """
    Extracts the nominees from the Wikipedia Awards table cell.
    Assumes:
      - Winner is in the first <li>
      - Nominees (if any) are in a nested <ul> inside that first <li>
    """
    nominees = []

    try:
        # find all <ul> elements in the cell
        ul_elements = table_cell.find_all("ul")

        if not ul_elements or len(ul_elements) < 1:
            logger.warning("No <ul> found in table_cell: %s", table_cell.get_text(strip = True))
            return []

        # first <ul> contains the winner in <li>, and possibly a nested <ul> with nominees
        first_ul = ul_elements[0]
        first_li = first_ul.find("li")

        if not first_li:
            logger.warning("No <li> found in first <ul>: %s", first_ul)
            return []

        # look for a nested <ul> inside the winner <li> (this contains nominees)
        sub_ul = first_li.find("ul")

        if not sub_ul:
            logger.info("No nominees <ul> found in winner <li>; only winner present.")
            return []

        # Each <li> in sub_ul is a nominee
        nominee_items = sub_ul.find_all("li")
        for nominee in nominee_items:
            nominee_text = nominee.get_text(separator=" ", strip=True)
            parsed_name = self.split_nominee_text(nominee_text)[0]
            nominees.append(parsed_name)

    except Exception as e:
        logger.warning("Unexpected error while extracting nominees: %s", str(e))

    return nominees

def scrape_all_wiki(start_year: int = 1929, end_year: int = 2025):
  urls = generate_oscar_urls(start_year, end_year)
  all_data = []

  for entry in tqdm(urls, desc = "Scraping Oscars Wiki pages"):
    try:
      scraper = WikipediaScraper(entry["url"])
      data = scraper.scrape_ceremony()
      data["ceremony_number"] = entry["ceremony_number"]
      data["year"] = entry["year"]
      all_data.append(data)
    except Exception as e:
      logger.error(f"Failed to scrape {entry['url']}: {e}")

  return all_data

def main(start_year: int = 1929, end_year: int = 2025):
  all_data = scrape_all_wiki(start_year, end_year)

  for ceremony in all_data:
    for award in ceremony["awards"]:
      print(
        ceremony["year"], 
        award.category,
        award.winner, 
        award.nominees
      )

if __name__ == "__main__":
  main()

# ! Awards table format is different for 18th (1946) - 49th (1977) awards. It uses separate cells for the awards/categories vs. it being in the same cell as the winners/nominees.