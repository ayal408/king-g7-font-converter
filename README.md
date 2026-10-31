# KING G7 Font Converter

ממיר פונטים וקטורי עבור הטלפון הכשר **KING G7**.

התוכנה ממירה קובצי `.ttf`, `.otf` ו-`.ttc` לפורמט `.lib` / SFON שבו משתמש המכשיר.

## הורדה

- [הורדת החבילה המלאה כ-ZIP](https://github.com/ayal408/king-g7-font-converter/releases/download/v1.0.0/KING-G7-Font-Converter.zip)
- [הורדת קובץ ההפעלה בלבד](https://github.com/ayal408/king-g7-font-converter/releases/download/v1.0.0/KingG7FontConverter.exe)
- [עמוד גרסה v1.0.0](https://github.com/ayal408/king-g7-font-converter/releases/tag/v1.0.0)

## שימוש

1. הורידו את `KingG7FontConverter.exe`.
2. לחצו על **בחר פונטים** ובחרו קובצי פונט.
3. בחרו תיקיית פלט.
4. לחצו על **המר עכשיו**.
5. העתיקו לטלפון תחילה קובץ LIB אחד לבדיקה.

אין צורך ב-Python כדי להפעיל את קובץ ה-EXE.

## קוד מקור

- `king_g7_font_converter_gui.py` — הממשק הגרפי.
- `ttf_to_king_lib.py` — מנוע ההמרה.
- `.github/workflows/build-release.yml` — בנייה אוטומטית ל-Windows ופרסום Release.

## הערות

- ההמרה מיועדת לפונטים הכוללים אלפבית עברי מלא.
- קובצי הפונט המקוריים אינם משתנים.
- התוכנה אינה חתומה דיגיטלית, ולכן Windows SmartScreen עשוי להציג אזהרה.
- מומלץ לבדוק כל פונט במכשיר לפני הפצה רחבה.
