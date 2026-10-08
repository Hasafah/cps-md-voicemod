from PySide6.QtGui import QPalette, QColor

def load_stylesheet(filename):
    with open(filename, "r") as f:
        return f.read()
    
    
def apply_black_n_green_palette(app):
    palette = QPalette()

    base = QColor(26, 26, 29)        # #1A1A1D (ciemne tło)
    alt_base = QColor(29, 93, 19)     # #1D5D13 (ciemny zielony)
    mid = QColor(51, 116, 24)        # #337418 (ciemny zielony #2)
    highlight = QColor(93, 214, 44)  # #5DD62C (jasny zielony )
    text = QColor(248, 248, 248)     # #F8F8F8 (jasny tekst #2 )

    palette.setColor(QPalette.Window, base)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, alt_base)  # Ciemniejszy zielony
    palette.setColor(QPalette.ToolTipBase, mid)          # Ciemny zielony
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, mid)              # Tło przycisków (ciemny zielony)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.Highlight, highlight)     # Zaznaczenie (jasny zielony)
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    # Stany nieaktywne
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))

    app.setPalette(palette)