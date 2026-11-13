import flet as ft
from app.ui.main_window import ScaNowApp


async def main(page: ft.Page):
    ScaNowApp(page)


if __name__ == "__main__":
    ft.run(main)
