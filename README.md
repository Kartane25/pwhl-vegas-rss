# PWHL Las Vegas official news → RSS → TrustyBot

A free scheduled GitHub Actions scraper for official team articles (no Discord webhook or bot token needed). GitHub Pages publishes `feed.xml`.

## Setup
1. Create a **public** GitHub repository, e.g. `pwhl-vegas-rss`.
2. Upload `build_feed.py`, `requirements.txt`, and `.github/workflows/update-feed.yml`, preserving that directory structure. You can unzip the project and upload via GitHub's **Add file → Upload files**, though GitHub's upload UI may not preserve dot-folder paths reliably; creating `.github/workflows/update-feed.yml` via **Add file → Create new file** is safest.
3. In repo **Settings → Pages**, under **Build and deployment**, choose **GitHub Actions**.
4. In **Actions → Update PWHL Las Vegas RSS → Run workflow**, run it manually.
5. After a successful deployment visit `https://YOUR_USERNAME.github.io/pwhl-vegas-rss/feed.xml` (replace with actual GitHub Pages deployment URL).
6. In Discord, add that RSS URL to TrustyBot in `#bot-testing` via `;rss add pwhl-official #bot-testing URL`.
7. Check `;rss listtags pwhl-official #bot-testing`, and use `;rss viewtags pwhl-official #bot-testing` to see which summary and image tags TrustyBot can consume. For an image, it may be necessary to use a specific template tag.

## Notes
- This reads articles only from the official Las Vegas team news path, not general league news.
- It checks every two hours; GitHub Actions scheduled executions can be delayed. The source website's markup might change, and the job will fail visibly rather than silently publish an empty feed.
- Article `guid` is the official article URL for stable item identity. TrustyBot decides whether to repost historic articles on initial subscription.
- Media is published using both `media:content` and `content:encoded` where an image is available. Discord image rendering depends on TrustyBot's capabilities; not guaranteed.
- Respect the original site's terms, attribution, and request frequency. This solution links to original articles rather than copying their full text.
