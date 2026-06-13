# Series Cover Stamper

A **Calibre** plugin that stamps the series book number onto your ebook covers.

## 🎯 Purpose

When you transfer books to an e-reader (like Kindle), they may appear in random order or not respect the series reading order. This forces you to open each book to find its number.

**Series Cover Stamper** solves this by adding a beautiful orange badge with the series volume number directly onto the book cover image. You can instantly see the correct reading order on your e-reader's library view.

## ✨ Features

- Detects books that belong to a series using Calibre's metadata
- Reads the volume/book number from the series index
- Draws an **orange scalloped badge** with the volume number on the cover
- Keeps a **backup** of the original cover (one-time, never overwritten)
- **Restore** button to revert covers to originals
- **Configurable** badge settings (7 positions, auto/manual size, shadow, etc.)
- **Multi-language** UI: English and Français
- **Batch processing** with a progress dialog
- Preserves your active **library filter/view** after processing

## 📥 Installation

1. Download the ZIP file from [Releases](https://github.com/macgile/calibre-series-cover-stamper/releases)
2. Open Calibre → Preferences → Advanced → Plugins
3. Click "Load plugin from file" and select the ZIP
4. Restart Calibre

## 👨‍💻 Author

**Gilles Macabies** — [macgile@gmail.com](mailto:macgile@gmail.com)