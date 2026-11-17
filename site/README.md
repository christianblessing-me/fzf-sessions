# Landing page

- Static HTML, CSS, and JavaScript. No build step or runtime packages.
- Fonts and the real product screenshot are served locally with the page.
- Font licenses are included in `assets/fonts/`.
- The interactive finder uses sample sessions. It does not read history or run commands.
- Supports GitHub Pages project paths: assets use relative links.
- The separate Website workflow publishes this folder to GitHub Pages.

## Preview

- Open `index.html` in your browser, or serve this folder locally:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

- Visit `http://127.0.0.1:8765`.
- Test searching, switching modes, toggling the preview, copying installation
  commands, and opening the full screenshot.
- Check the layout at desktop and phone widths.

## Publish on GitHub Pages

- Website address: `https://fzf-sessions.christianblessing.me`.
- After approval, commit and push the page and `.github/workflows/pages.yml`.
- In this repository's Settings → Pages, choose **GitHub Actions** as the source.
- Set the custom domain to `fzf-sessions.christianblessing.me` before adding DNS.
- In the DNS settings for `christianblessing.me`, add a CNAME record:
  - Name: `fzf-sessions`.
  - Target: `christianblessing-me.github.io` (no protocol or repository path).
- Keep the existing blog domain and DNS records unchanged.
- Once the DNS check and certificate are ready, enable **Enforce HTTPS**.
- Run the **Website** workflow manually if the first push happened before Pages was enabled.
- Later pushes to `main` deploy when `site/` or the website workflow changes.
- The workflow publishes `site/` directly; no build step is needed.
- The custom domain is stored in GitHub's Pages settings. An Actions deployment does not need a `CNAME` file.
- Keep the Python tool and its existing release process separate from the website.
- Update the release badge/link in `index.html` when promoting a new tool version.
- The page has no analytics, forms, accounts, or background API requests.
