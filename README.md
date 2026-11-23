# Ship Proximity Map

A live website showing **Brilliance of the Seas** and **Margaritaville at Sea Paradise** on a map, with the distance between them. It turns green when they are within your chosen distance (default 25 NM).

Two data sources work together:
- **Live feed:** the page connects to AISstream.io straight from your browser, using a key you paste into Settings.
- **Scheduled check:** a GitHub Action saves both positions to `positions.json` every ~10 minutes. The page reads this file when there is no key, or when the browser can't reach the live feed.

## Setup (about 10 minutes, all in a web browser)

1. **AISstream key.** Go to https://aisstream.io, sign in with GitHub, create an API key.
2. **GitHub repo.** Create a new **public** repository (for example `ship-map`).
3. **Upload the files.** Use Add file > Upload files and drop in `index.html`, `proximity_alert.py` and this README. Then Add file > Create new file, type `.github/workflows/ship-alert.yml` as the name, and paste in the contents of `ship-alert.yml`.
4. **Add the secret.** Settings > Secrets and variables > Actions > New repository secret. Name `AISSTREAM_API_KEY`, value is your key. (`NTFY_TOPIC` is optional and only needed for phone notifications.)
5. **Allow the workflow to save.** Settings > Actions > General > Workflow permissions > Read and write permissions > Save.
6. **Run it once.** Actions tab > Ship proximity alert > Run workflow. After it finishes, `positions.json` appears in the repo.
7. **Turn on the website.** Settings > Pages > Source: Deploy from a branch > `main` / root > Save. After a minute your site is at `https://YOUR-USERNAME.github.io/ship-map/`.
8. **Open the site**, open Settings on the page, paste your AISstream key, and tap Save and connect. The key stays in your browser only.

## Notes

- If the live feed shows "unavailable", the page keeps working from the scheduled positions. AISstream may not allow direct browser connections, and this was not tested from here.
- A ship only shows when its AIS signal is received. At sea, gaps are normal.
- The scheduler adds a small commit every ~10 minutes. That is expected.
- Sound and browser notifications only fire while the page is open. For alerts while the page is closed, set `NTFY_TOPIC` and use the ntfy phone app.
