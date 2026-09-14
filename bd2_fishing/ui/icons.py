"""按显示缩放绘制导航线条图标，无字体图标依赖。"""

from PIL import Image, ImageDraw, ImageTk

from bd2_fishing.ui.theme import MUTED


def navigation_icon(master, name):
    size = round(20 * master.winfo_fpixels("1i") / 96)
    bitmap = Image.new("RGBA", (80, 80))
    pen = ImageDraw.Draw(bitmap)
    line = {"fill": MUTED, "width": 5}
    if name == "run":
        pen.line([(12, 68), (52, 12), (64, 12), (64, 52)], **line)
        pen.arc((48, 44, 64, 64), 0, 180, **line)
    elif name == "catalogue":
        pen.rounded_rectangle((10, 14, 70, 66), radius=5, outline=MUTED, width=5)
        pen.line([(40, 14), (40, 66)], **line)
        pen.line([(19, 29), (30, 29)], **line)
        pen.line([(49, 29), (61, 29)], **line)
    elif name == "targets":
        pen.ellipse((12, 12, 68, 68), outline=MUTED, width=5)
        pen.ellipse((27, 27, 53, 53), outline=MUTED, width=5)
        pen.ellipse((36, 36, 44, 44), fill=MUTED)
    elif name == "catches":
        pen.ellipse((9, 21, 58, 59), outline=MUTED, width=5)
        pen.line([(56, 34), (71, 24), (71, 56), (56, 46)], **line)
        pen.ellipse((20, 32, 27, 39), fill=MUTED)
    else:
        for x, y in ((21, 27), (40, 51), (59, 34)):
            pen.line([(x, 13), (x, 67)], **line)
            pen.ellipse((x - 6, y - 6, x + 6, y + 6), fill="white", outline=MUTED, width=4)
    return ImageTk.PhotoImage(bitmap.resize((size, size), Image.Resampling.LANCZOS), master=master)
