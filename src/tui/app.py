"""Main TUI Application for Turtle-CANSLIM."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import unicodedata

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    ProgressBar,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from src.core.config import get_settings, TradingMode


def _truncate_wide(text: str, max_width: int = 12) -> str:
    """Truncate string by display width, accounting for CJK wide characters."""
    width = 0
    result: list[str] = []
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if width + w > max_width:
            break
        result.append(ch)
        width += w
    return "".join(result)


class ScreeningProgress:
    def __init__(self) -> None:
        self.total: int = 0
        self.current: int = 0
        self.status: str = "대기"
        self.is_running: bool = False

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.current / self.total) * 100


class StatusPanel(Static):
    """Status panel showing current system state."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._settings = get_settings()

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def on_mount(self) -> None:
        self.update_status()

    def update_status(
        self,
        positions: int = 0,
        units: int = 0,
        candidates: int = 0,
        last_scan: str = "-",
        trading_krx: bool = False,
        trading_us: bool = False,
    ) -> None:
        mode = self._settings.trading_mode.value.upper()
        mode_color = "green" if mode == "PAPER" else "red"

        krx_status = "[green bold]ON[/]" if trading_krx else "[dim]OFF[/]"
        us_status = "[green bold]ON[/]" if trading_us else "[dim]OFF[/]"

        content = self.query_one("#status-content", Static)
        content.update(
            f"[bold]모드:[/] [{mode_color}]{mode}[/]  "
            f"[bold]KRX:[/] {krx_status}  "
            f"[bold]US:[/] {us_status}  "
            f"[bold]포지션:[/] {positions}  "
            f"[bold]유닛:[/] {units}/20  "
            f"[bold]후보종목:[/] {candidates}  "
            f"[bold]최근스캔:[/] {last_scan}"
        )


class PortfolioTable(Static):
    """Portfolio positions table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="portfolio-table")

    def on_mount(self) -> None:
        table = self.query_one("#portfolio-table", DataTable)
        table.add_columns(
            "종목코드", "종목명", "수량", "매입가", "현재가", "손익", "손익%", "유닛", "손절가"
        )
        table.cursor_type = "row"
        table.zebra_stripes = True

    def update_data(self, positions: list[dict]) -> None:
        table = self.query_one("#portfolio-table", DataTable)
        table.clear()

        for pos in positions:
            pnl = pos.get("pnl", 0)
            pnl_pct = pos.get("pnl_pct", 0)
            pnl_color = "green" if pnl >= 0 else "red"

            table.add_row(
                pos.get("symbol", ""),
                _truncate_wide(pos.get("name", ""), 15),
                str(pos.get("quantity", 0)),
                f"{pos.get('entry_price', 0):,.0f}",
                f"{pos.get('current_price', 0):,.0f}",
                Text(f"{pnl:+,.0f}", style=pnl_color),
                Text(f"{pnl_pct:+.1f}%", style=pnl_color),
                str(pos.get("units", 0)),
                f"{pos.get('stop_loss', 0):,.0f}",
            )


class CandidatesTable(Static):
    """CANSLIM candidates table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="candidates-table")

    def on_mount(self) -> None:
        table = self.query_one("#candidates-table", DataTable)
        table.add_columns(
            "종목코드", "종목명", "점수", "C", "A", "N", "S", "L", "I", "M", "RS", "EPS%", "매출%", "ROE"
        )
        table.cursor_type = "row"
        table.zebra_stripes = True

    def update_data(self, candidates: list[dict]) -> None:
        table = self.query_one("#candidates-table", DataTable)
        table.clear()

        for c in candidates:

            def indicator(passed: bool | None) -> Text:
                if passed is None:
                    return Text("-", style="dim")
                return Text("✓", style="green") if passed else Text("✗", style="red")

            eps_growth = c.get("eps_growth")
            eps_str = f"{eps_growth:.0%}" if eps_growth else "-"

            revenue_growth = c.get("revenue_growth")
            revenue_str = f"{revenue_growth:.0%}" if revenue_growth else "-"

            roe = c.get("roe")
            roe_str = f"{roe:.1%}" if roe else "-"

            table.add_row(
                c.get("symbol", ""),
                _truncate_wide(c.get("name", ""), 12),
                str(c.get("score", 0)),
                indicator(c.get("c")),
                indicator(c.get("a")),
                indicator(c.get("n")),
                indicator(c.get("s")),
                indicator(c.get("l")),
                indicator(c.get("i")),
                indicator(c.get("m")),
                str(c.get("rs", "-")),
                eps_str,
                revenue_str,
                roe_str,
            )


class SignalsTable(Static):
    """Trading signals table."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="signals-table")

    def on_mount(self) -> None:
        table = self.query_one("#signals-table", DataTable)
        table.add_columns("시간", "종목코드", "유형", "시스템", "가격", "ATR", "손절가", "상태")
        table.cursor_type = "row"
        table.zebra_stripes = True

    def update_data(self, signals: list[dict]) -> None:
        table = self.query_one("#signals-table", DataTable)
        table.clear()

        for sig in signals:
            sig_type = sig.get("type", "")
            type_color = "green" if "ENTRY" in sig_type else "red"

            status = sig.get("status", "")
            status_color = "green" if status == "FILLED" else "yellow"

            table.add_row(
                sig.get("time", ""),
                sig.get("symbol", ""),
                Text(sig_type, style=type_color),
                f"S{sig.get('system', '')}",
                f"{sig.get('price', 0):,.0f}",
                f"{sig.get('atr', 0):,.0f}",
                f"{sig.get('stop', 0):,.0f}",
                Text(status, style=status_color),
            )


class KeyboardShortcutsPanel(Static):
    """Keyboard shortcuts display panel."""

    def compose(self) -> ComposeResult:
        yield Static(id="shortcuts-content")

    def on_mount(self) -> None:
        self.update_shortcuts()

    def update_shortcuts(self) -> None:
        content = self.query_one("#shortcuts-content", Static)

        text = """[bold cyan]═══ 전역 단축키 ═══[/]

[bold yellow]Q[/]    종료
[bold yellow]R[/]    데이터 새로고침
[bold yellow]U[/]    데이터 갱신 (최신 가격)
[bold yellow]S[/]    전체 스크리닝 (KRX + US)
[bold yellow]K[/]    KRX 스크리닝
[bold yellow]N[/]    US 스크리닝
[bold yellow]T[/]    KRX 트레이딩 시작/중지
[bold yellow]Y[/]    US 트레이딩 시작/중지
[bold yellow]H[/]    매매 내역 새로고침
[bold yellow]M[/]    모의/실전 모드 전환
[bold yellow]D[/]    다크/라이트 모드 전환

[bold cyan]═══ 탭 전환 ═══[/]

[bold yellow]←/→[/]  이전/다음 탭 전환
[bold yellow]1-7[/]  탭 직접 선택 (Portfolio/Candidates/Signals/매매내역/Log/Settings/Shortcuts)

[bold cyan]═══ 테이블 내 이동 ═══[/]

[bold yellow]↑/↓[/]  행 이동

[bold cyan]═══ 사용 팁 ═══[/]

• 상단 상태바에서 KRX/US 트레이딩 ON/OFF 확인
• [bold]S[/] 키: 전체 데이터 자동 수집 후 스크리닝
• Log 탭(4)에서 전체 매매 로그 확인
• 로그는 logs/ 디렉토리에 자동 저장됨
"""
        content.update(text)


class TradeHistoryTable(Static):

    def compose(self) -> ComposeResult:
        yield Static(id="trade-stats-panel")
        yield DataTable(id="trade-history-table")

    def on_mount(self) -> None:
        table = self.query_one("#trade-history-table", DataTable)
        table.add_columns(
            "종목코드", "종목명", "매수일", "매도일", "매수가", "매도가", "손익%", "보유일", "청산사유"
        )
        table.cursor_type = "row"
        table.zebra_stripes = True

    def update_stats(self, stats_text: str) -> None:
        panel = self.query_one("#trade-stats-panel", Static)
        panel.update(stats_text)

    def update_data(self, trades: list[dict]) -> None:
        table = self.query_one("#trade-history-table", DataTable)
        table.clear()

        for t in trades:
            pnl_pct = t.get("pnl_pct", 0)
            pnl_color = "green" if pnl_pct >= 0 else "red"

            table.add_row(
                t.get("symbol", ""),
                _truncate_wide(t.get("name", ""), 12),
                t.get("entry_date", ""),
                t.get("exit_date", ""),
                f"{t.get('entry_price', 0):,.0f}",
                f"{t.get('exit_price', 0):,.0f}",
                Text(f"{pnl_pct:+.2f}%", style=pnl_color),
                str(t.get("holding_days", 0)),
                t.get("exit_reason", ""),
            )


class SettingsPanel(Static):
    """Settings display panel."""

    def compose(self) -> ComposeResult:
        yield Static(id="settings-content")

    def on_mount(self) -> None:
        self.update_settings()

    def update_settings(self) -> None:
        settings = get_settings()
        content = self.query_one("#settings-content", Static)

        mode_color = "green" if settings.trading_mode == TradingMode.PAPER else "red"

        text = f"""[bold cyan]═══ 트레이딩 설정 ═══[/]

[bold]모드:[/]          [{mode_color}]{settings.trading_mode.value.upper()}[/]
[bold]시장:[/]          {settings.market.value.upper()}

[bold cyan]═══ CANSLIM 기준 ═══[/]

[bold]C - EPS 성장률:[/]      >= {settings.canslim.c_eps_growth_min:.0%}
[bold]C - 매출 성장률:[/]     >= {settings.canslim.c_revenue_growth_min:.0%}
[bold]A - 연간 EPS:[/]        >= {settings.canslim.a_eps_growth_min:.0%}
[bold]L - RS 등급:[/]         >= {settings.canslim.l_rs_min}
[bold]I - 기관 보유율:[/]     >= {settings.canslim.i_institution_min:.0%}

[bold cyan]═══ 터틀 트레이딩 ═══[/]

[bold]시스템1 진입:[/]   {settings.turtle.system1_entry_period}일 돌파
[bold]시스템1 청산:[/]   {settings.turtle.system1_exit_period}일 붕괴
[bold]시스템2 진입:[/]   {settings.turtle.system2_entry_period}일 돌파
[bold]시스템2 청산:[/]   {settings.turtle.system2_exit_period}일 붕괴
[bold]ATR 기간:[/]       {settings.turtle.atr_period}일
[bold]피라미딩 간격:[/]  {settings.turtle.pyramid_unit_interval}N

[bold cyan]═══ 리스크 관리 ═══[/]

[bold]유닛당 리스크:[/]    {settings.risk.risk_per_unit:.0%}
[bold]종목당 최대유닛:[/]  {settings.risk.max_units_per_stock}
[bold]총 최대유닛:[/]      {settings.risk.max_units_total}
[bold]손절 ATR:[/]         {settings.risk.stop_loss_atr_multiplier}N
[bold]최대 손절:[/]        {settings.risk.stop_loss_max_percent:.0%}

[bold cyan]═══ API 상태 ═══[/]

[bold]한투 API:[/]   {"✓ 설정됨" if settings.kis_paper_app_key else "✗ 미설정"}
[bold]DART API:[/]   {"✓ 설정됨" if settings.dart_api_key else "✗ 미설정"}
[bold]SEC EDGAR:[/]  {"✓ 설정됨" if settings.sec_user_agent else "✗ 미설정"}
[bold]텔레그램:[/]   {"✓ 설정됨" if settings.telegram_bot_token else "✗ 미설정"}
[bold]데이터베이스:[/] {"✓ 설정됨" if settings.database_url else "✗ 미설정"}
"""
        content.update(text)


class TurtleCANSLIMApp(App):

    TITLE = "터틀-캔슬림"
    SUB_TITLE = "CANSLIM + 터틀 트레이딩 시스템"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        background: $surface;
    }

    #status-panel {
        height: 3;
        background: $primary-background;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #main-content {
        height: 1fr;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1;
    }

    DataTable {
        height: 1fr;
    }

    #log-panel {
        height: 10;
        border-top: solid $primary;
    }

    #log-tab-panel {
        height: 1fr;
        background: $surface-darken-1;
    }

    RichLog {
        height: 1fr;
        background: $surface-darken-1;
    }

    SettingsPanel {
        padding: 1;
    }

    #settings-content {
        height: 1fr;
    }

    .loading {
        align: center middle;
        height: 1fr;
    }

    #progress-status {
        height: 1;
        padding: 0 1;
        background: $primary-background;
    }

    #progress-bar {
        height: 1;
        padding: 0 1;
    }

    .progress-hidden {
        display: none;
    }

    .progress-visible {
        display: block;
    }
    """

    _TAB_IDS = ["portfolio", "candidates", "signals", "trade-history", "log", "settings", "shortcuts"]

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("u", "update_data", "Update"),
        Binding("s", "run_screening_default", "Screen"),
        Binding("k", "run_screening_krx", "KRX"),
        Binding("n", "run_screening_us", "US"),
        Binding("t", "toggle_trading_krx", "KRX Trade"),
        Binding("y", "toggle_trading_us", "US Trade"),
        Binding("h", "refresh_trade_history", "Trade History"),
        Binding("m", "toggle_trading_mode", "Mode"),
        Binding("d", "toggle_dark", "Dark/Light"),
        Binding("left", "prev_tab", "Prev Tab"),
        Binding("right", "next_tab", "Next Tab"),
        Binding("1", "show_tab('portfolio')", "Portfolio", show=False),
        Binding("2", "show_tab('candidates')", "Candidates", show=False),
        Binding("3", "show_tab('signals')", "Signals", show=False),
        Binding("4", "show_tab('trade-history')", "Trade History", show=False),
        Binding("5", "show_tab('log')", "Log", show=False),
        Binding("6", "show_tab('settings')", "Settings", show=False),
        Binding("7", "show_tab('shortcuts')", "Shortcuts", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = get_settings()
        self._positions: list[dict] = []
        self._candidates: list[dict] = []
        self._signals: list[dict] = []
        self._screening_progress = ScreeningProgress()
        self._trading_active_krx: bool = False
        self._trading_active_us: bool = False
        self._log_file = self._init_log_file()

    @staticmethod
    def _init_log_file() -> Path | None:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"tui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        try:
            log_path.touch()
            return log_path
        except OSError:
            return None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusPanel(id="status-panel")
        with Container(id="main-content"):
            with TabbedContent():
                with TabPane("Portfolio", id="portfolio"):
                    yield PortfolioTable()
                with TabPane("Candidates", id="candidates"):
                    yield CandidatesTable()
                with TabPane("Signals", id="signals"):
                    yield SignalsTable()
                with TabPane("매매 내역", id="trade-history"):
                    yield TradeHistoryTable(id="trade-history-tab")
                with TabPane("Log", id="log"):
                    yield RichLog(id="log-tab-panel", highlight=True, markup=True)
                with TabPane("Settings", id="settings"):
                    with ScrollableContainer():
                        yield SettingsPanel()
                with TabPane("Shortcuts", id="shortcuts"):
                    with ScrollableContainer():
                        yield KeyboardShortcutsPanel()
        yield Static(id="progress-status", classes="progress-hidden")
        yield ProgressBar(id="progress-bar", total=100, show_eta=False, classes="progress-hidden")
        yield RichLog(id="log-panel", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.log_message("[bold green]터틀-캔슬림 TUI 시작됨[/]")
        self.log_message(f"모드: {self._settings.trading_mode.value.upper()}")
        if self._log_file:
            self.log_message(f"[dim]로그 파일: {self._log_file}[/]")
        self.log_message(
            "[bold]R[/] Refresh | [bold]K[/] KRX | [bold]N[/] US | [bold]S[/] Screen | [bold]T[/] KRX Trade | [bold]Y[/] US Trade | [bold]Q[/] Quit"
        )
        term = os.environ.get("TERM_PROGRAM", "")
        if term in ("Apple_Terminal",):
            self.log_message(
                "[yellow]⚠ 한글이 깨져 보이면 iTerm2/WezTerm/Kitty 터미널을 사용하세요[/]"
            )
        self.refresh_data()
        self._restore_trading_state()

    @work(exclusive=False)
    async def _restore_trading_state(self) -> None:
        try:
            from src.core.database import get_db_manager
            from src.data.repositories import TradingStateRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = TradingStateRepository(session)
                krx_was_active = await repo.get_trading_state("krx")
                us_was_active = await repo.get_trading_state("us")

            if krx_was_active:
                self.log_message("[cyan]이전 KRX 트레이딩 상태 복원 중...[/]")
                self.action_run_trading_krx()
            if us_was_active:
                self.log_message("[cyan]이전 US 트레이딩 상태 복원 중...[/]")
                self.action_run_trading_us()
        except Exception as e:
            self.log_message(f"[red]트레이딩 상태 복원 실패: {e}[/]")

    def log_message(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[dim]{timestamp}[/] {message}"

        self.query_one("#log-panel", RichLog).write(formatted)
        self.query_one("#log-tab-panel", RichLog).write(formatted)

        if self._log_file:
            try:
                plain = re.sub(r"\[/?[^\]]*\]", "", f"{timestamp} {message}")
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(plain + "\n")
            except OSError:
                pass

    def action_refresh(self) -> None:
        self.log_message("데이터 새로고침 중...")
        self.refresh_data()

    @work(exclusive=True)
    async def action_update_data(self) -> None:
        self.log_message("[yellow]데이터 갱신 시작...[/]")
        try:
            from src.core.database import get_db_manager
            from src.data.auto_fetcher import AutoDataFetcher

            market = self._settings.market.value
            db = get_db_manager()

            async with db.session() as session:
                fetcher = AutoDataFetcher(session)
                has = await fetcher.has_data(market)

                if not has:
                    self.log_message("데이터가 없습니다. 전체 수집을 시작합니다...")
                    await fetcher.fetch_and_store(market, progress_callback=self.log_message)
                else:
                    stale = await fetcher.is_data_stale(market)
                    if not stale:
                        self.log_message("[green]데이터가 최신 상태입니다.[/]")
                        return
                    latest = await fetcher.get_latest_price_date(market)
                    age = (datetime.now() - latest).days if latest else 0
                    self.log_message(f"마지막 데이터: {age}일 전. 최신 가격으로 업데이트 중...")
                    await fetcher.update_prices(market, progress_callback=self.log_message)

            self.log_message("[green]데이터 갱신 완료[/]")
            await self._load_candidates()
            self._update_status()

        except Exception as e:
            self.log_message(f"[red]데이터 갱신 오류: {e}[/]")

    def _show_progress(self, status: str, percentage: float = 0) -> None:
        progress_status = self.query_one("#progress-status", Static)
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        progress_status.remove_class("progress-hidden")
        progress_status.add_class("progress-visible")
        progress_bar.remove_class("progress-hidden")
        progress_bar.add_class("progress-visible")

        progress_status.update(f"[bold yellow]{status}[/] ({percentage:.1f}%)")
        progress_bar.update(progress=percentage)

    def _hide_progress(self) -> None:
        progress_status = self.query_one("#progress-status", Static)
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        progress_status.remove_class("progress-visible")
        progress_status.add_class("progress-hidden")
        progress_bar.remove_class("progress-visible")
        progress_bar.add_class("progress-hidden")

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    def action_toggle_trading_mode(self) -> None:
        if self._settings.trading_mode == TradingMode.PAPER:
            self._settings.trading_mode = TradingMode.LIVE
            self.log_message("[bold red]⚠ 실전 모드로 전환됨! 실제 매매가 실행됩니다.[/]")
        else:
            self._settings.trading_mode = TradingMode.PAPER
            self.log_message("[bold green]모의 모드로 전환됨[/]")
        self._update_status()

    def action_show_tab(self, tab: str) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = tab

    def action_prev_tab(self) -> None:
        tabbed = self.query_one(TabbedContent)
        current = tabbed.active
        idx = self._TAB_IDS.index(current) if current in self._TAB_IDS else 0
        tabbed.active = self._TAB_IDS[(idx - 1) % len(self._TAB_IDS)]

    def action_next_tab(self) -> None:
        tabbed = self.query_one(TabbedContent)
        current = tabbed.active
        idx = self._TAB_IDS.index(current) if current in self._TAB_IDS else 0
        tabbed.active = self._TAB_IDS[(idx + 1) % len(self._TAB_IDS)]

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        try:
            await self._load_portfolio()
            await self._load_candidates()
            await self._load_signals()
            await self._sync_daemon_trading_state()
            self._update_status()
            self.log_message("[green]데이터 새로고침 완료[/]")
        except Exception as e:
            self.log_message(f"[red]데이터 새로고침 오류: {e}[/]")

    async def _sync_daemon_trading_state(self) -> None:
        try:
            from src.core.database import get_db_manager
            from src.data.repositories import TradingStateRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = TradingStateRepository(session)
                krx_active = await repo.is_trading_active("krx")
                us_active = await repo.is_trading_active("us")

            if krx_active and not self._trading_active_krx:
                self._trading_active_krx = True
                self.log_message("[cyan]데몬 KRX 트레이딩 활성 상태 감지[/]")

            if us_active and not self._trading_active_us:
                self._trading_active_us = True
                self.log_message("[cyan]데몬 US 트레이딩 활성 상태 감지[/]")

            if not krx_active and self._trading_active_krx:
                self._trading_active_krx = False

            if not us_active and self._trading_active_us:
                self._trading_active_us = False

        except Exception:
            pass

    async def _load_portfolio(self) -> None:
        """Load portfolio positions from database."""
        # In production, this would load from database
        # For now, using sample data structure
        self._positions = []

        try:
            from src.core.database import get_db_manager
            from src.data.repositories import PositionRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = PositionRepository(session)
                positions = await repo.get_open_positions()

                for pos in positions:
                    self._positions.append(
                        {
                            "symbol": pos.stock.symbol if pos.stock else "",
                            "name": pos.stock.name if pos.stock else "",
                            "quantity": pos.quantity,
                            "entry_price": float(pos.entry_price),
                            "current_price": float(pos.entry_price),  # Would need live price
                            "pnl": 0,
                            "pnl_pct": 0,
                            "units": pos.units,
                            "stop_loss": float(pos.stop_loss_price) if pos.stop_loss_price else 0,
                        }
                    )
        except Exception:
            pass  # Database not available, use empty list

        portfolio_table = self.query_one(PortfolioTable)
        portfolio_table.update_data(self._positions)

    async def _load_candidates(self) -> None:
        """Load CANSLIM candidates from database."""
        self._candidates = []

        try:
            from src.core.database import get_db_manager
            from src.data.repositories import CANSLIMScoreRepository, StockRepository, FundamentalRepository

            db = get_db_manager()
            async with db.session() as session:
                score_repo = CANSLIMScoreRepository(session)
                stock_repo = StockRepository(session)
                fundamental_repo = FundamentalRepository(session)
                scores = await score_repo.get_candidates(min_score=4)

                for score in scores:
                    stock = await stock_repo.get_by_id(score.stock_id)
                    if stock:
                        roe_value = None
                        try:
                            latest_annual = await fundamental_repo.get_latest_annual(score.stock_id, years=1)
                            if latest_annual and latest_annual[0].roe is not None:
                                roe_value = float(latest_annual[0].roe)
                            else:
                                latest_q = await fundamental_repo.get_latest_quarterly(score.stock_id)
                                if latest_q and latest_q.roe is not None:
                                    roe_value = float(latest_q.roe)
                        except Exception:
                            pass

                        self._candidates.append(
                            {
                                "symbol": stock.symbol,
                                "name": stock.name,
                                "score": score.total_score,
                                "c": score.c_score,
                                "a": score.a_score,
                                "n": score.n_score,
                                "s": score.s_score,
                                "l": score.l_score,
                                "i": score.i_score,
                                "m": score.m_score,
                                "rs": score.rs_rating,
                                "eps_growth": float(score.c_eps_growth)
                                if score.c_eps_growth
                                else None,
                                "revenue_growth": float(score.c_revenue_growth)
                                if score.c_revenue_growth
                                else None,
                                "roe": roe_value,
                            }
                        )
        except Exception:
            pass

        candidates_table = self.query_one(CandidatesTable)
        candidates_table.update_data(self._candidates)

    async def _load_signals(self) -> None:
        """Load recent signals from database."""
        self._signals = []

        try:
            from src.core.database import get_db_manager
            from src.data.repositories import SignalRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = SignalRepository(session)
                signals = await repo.get_recent(limit=50)

                for sig in signals:
                    self._signals.append(
                        {
                            "time": sig.timestamp.strftime("%m-%d %H:%M") if sig.timestamp else "",
                            "symbol": sig.stock.symbol if sig.stock else "",
                            "type": sig.signal_type,
                            "system": sig.system,
                            "price": float(sig.price),
                            "atr": float(sig.atr_n) if sig.atr_n else 0,
                            "stop": 0,
                            "status": "FILLED" if sig.is_executed else "PENDING",
                        }
                    )
        except Exception:
            pass

        signals_table = self.query_one(SignalsTable)
        signals_table.update_data(self._signals)

    def _update_status(self) -> None:
        total_units = sum(p.get("units", 0) for p in self._positions)
        last_scan = datetime.now().strftime("%H:%M:%S")

        status_panel = self.query_one(StatusPanel)
        status_panel.update_status(
            positions=len(self._positions),
            units=total_units,
            candidates=len(self._candidates),
            last_scan=last_scan,
            trading_krx=self._trading_active_krx,
            trading_us=self._trading_active_us,
        )

    @work(exclusive=False)
    async def action_refresh_trade_history(self) -> None:
        self.log_message("[yellow]매매 내역 조회 중...[/]")
        try:
            from src.core.database import get_db_manager
            from src.data.repositories import PositionRepository, StockRepository
            from src.execution.performance import PerformanceTracker

            db = get_db_manager()
            async with db.session() as session:
                position_repo = PositionRepository(session)
                stock_repo = StockRepository(session)

                closed_positions = await position_repo.get_closed_positions(limit=50)
                open_positions = await position_repo.get_open_positions()
                stats = PerformanceTracker.calculate(closed_positions, open_positions)

                stats_text = (
                    f"[bold cyan]──── 전체 성과 ────[/]\n"
                    f"[bold]총 거래:[/] {stats.total_trades}건  "
                    f"[bold]승률:[/] {stats.win_rate:.1%} ({stats.win_count}승 {stats.loss_count}패)  "
                )
                if stats.win_count > 0:
                    stats_text += (
                        f"[bold]평균 수익:[/] [green]{stats.avg_win_pct:+.2%}[/]  "
                        f"[bold]최대 수익:[/] [green]{stats.max_win_pct:+.2%}[/]\n"
                    )
                if stats.loss_count > 0:
                    stats_text += (
                        f"[bold]평균 손실:[/] [red]{stats.avg_loss_pct:+.2%}[/]  "
                        f"[bold]최대 손실:[/] [red]{stats.max_loss_pct:+.2%}[/]  "
                    )
                if stats.avg_holding_days > 0:
                    stats_text += (
                        f"[bold]평균 보유:[/] {stats.avg_holding_days:.1f}일  "
                        f"[bold]최장:[/] {stats.max_holding_days}일  "
                    )
                if stats.profit_factor > 0:
                    stats_text += f"[bold]손익비:[/] {stats.profit_factor:.2f}  "
                if stats.open_positions > 0:
                    stats_text += (
                        f"\n[bold]보유 중:[/] {stats.open_positions}종목 ({stats.open_units} units)"
                    )

                trades: list[dict] = []
                for pos in closed_positions:
                    stock = await stock_repo.get_by_id(pos.stock_id)
                    symbol = stock.symbol if stock else ""
                    name = stock.name if stock else ""
                    entry_dt = pos.entry_date.strftime("%Y-%m-%d") if pos.entry_date else ""
                    exit_dt = pos.exit_date.strftime("%Y-%m-%d") if pos.exit_date else ""
                    holding = (pos.exit_date - pos.entry_date).days if pos.entry_date and pos.exit_date else 0

                    trades.append({
                        "symbol": symbol,
                        "name": name,
                        "entry_date": entry_dt,
                        "exit_date": exit_dt,
                        "entry_price": float(pos.entry_price),
                        "exit_price": float(pos.exit_price) if pos.exit_price else 0,
                        "pnl_pct": float(pos.pnl_percent) if pos.pnl_percent else 0,
                        "holding_days": max(holding, 0),
                        "exit_reason": pos.exit_reason or "",
                    })

            trade_history_table = self.query_one(TradeHistoryTable)
            trade_history_table.update_stats(stats_text)
            trade_history_table.update_data(trades)
            self.log_message(f"[green]매매 내역 조회 완료: {len(trades)}건[/]")

        except Exception as e:
            self.log_message(f"[red]매매 내역 조회 오류: {e}[/]")

    def action_run_screening_default(self) -> None:
        """전체 스크리닝 (설정된 마켓 기준)."""
        self._run_screening_for_market("both")

    def action_run_screening_krx(self) -> None:
        """KRX만 스크리닝."""
        self._run_screening_for_market("krx")

    def action_run_screening_us(self) -> None:
        """US만 스크리닝."""
        self._run_screening_for_market("us")

    @work(exclusive=True)
    async def _run_screening_for_market(self, market: str) -> None:
        """지정된 마켓에 대해 CANSLIM 스크리닝 실행."""
        market_labels = {"krx": "KRX", "us": "US", "both": "전체"}
        label = market_labels.get(market, market.upper())
        self.log_message(f"[yellow]{label} CANSLIM 스크리닝 시작...[/]")

        try:
            from src.core.database import get_db_manager
            from src.data.auto_fetcher import AutoDataFetcher
            from src.data.repositories import (
                StockRepository,
                FundamentalRepository,
                DailyPriceRepository,
                CANSLIMScoreRepository,
            )
            from src.screener.canslim import CANSLIMScreener

            db = get_db_manager()

            async with db.session() as fetch_session:
                fetcher = AutoDataFetcher(fetch_session)
                data_ready = await fetcher.ensure_data(
                    market,
                    progress_callback=self.log_message,
                )
                if not data_ready:
                    self.log_message("[bold red]데이터 수집에 실패했습니다.[/]")
                    return

            async with db.session() as session:
                stock_repo = StockRepository(session)
                stocks = await stock_repo.get_all_active(market)

                if not stocks:
                    self.log_message("[bold red]종목 데이터가 없습니다.[/]")
                    return

                self.log_message(f"[cyan]{len(stocks)}개 종목 분석 중...[/]")
                self._show_progress("스크리닝 진행 중", 0)

                screener = CANSLIMScreener(
                    stock_repo=stock_repo,
                    fundamental_repo=FundamentalRepository(session),
                    price_repo=DailyPriceRepository(session),
                    score_repo=CANSLIMScoreRepository(session),
                )

                results = await screener.screen(market)
                candidates = [r for r in results if r.is_candidate]

                self._hide_progress()

                if candidates:
                    self.log_message(
                        f"[green]{label} 스크리닝 완료: {len(candidates)}개 후보 발견[/]"
                    )
                else:
                    self.log_message(
                        f"[yellow]{label} 스크리닝 완료: 후보 없음 (총 {len(results)}개 분석)[/]"
                    )
                    if results:
                        passed_counts = {"C": 0, "A": 0, "N": 0, "S": 0, "L": 0, "I": 0, "M": 0}
                        for r in results:
                            if r.c_result and r.c_result.passed:
                                passed_counts["C"] += 1
                            if r.a_result and r.a_result.passed:
                                passed_counts["A"] += 1
                            if r.n_result and r.n_result.passed:
                                passed_counts["N"] += 1
                            if r.s_result and r.s_result.passed:
                                passed_counts["S"] += 1
                            if r.l_result and r.l_result.passed:
                                passed_counts["L"] += 1
                            if r.i_result and r.i_result.passed:
                                passed_counts["I"] += 1
                            if r.m_result and r.m_result.passed:
                                passed_counts["M"] += 1
                        self.log_message(
                            f"[dim]통과율: C={passed_counts['C']} A={passed_counts['A']} N={passed_counts['N']} S={passed_counts['S']} L={passed_counts['L']} I={passed_counts['I']} M={passed_counts['M']}[/]"
                        )

            await self._load_candidates()
            self._update_status()

        except Exception as e:
            self._hide_progress()
            self.log_message(f"[red]{label} 스크리닝 오류: {e}[/]")

    @work(group="trading_krx")
    async def action_run_trading_krx(self) -> None:
        """Run continuous KRX trading until user stops."""
        await self._run_trading_loop("krx")

    @work(group="trading_us")
    async def action_run_trading_us(self) -> None:
        """Run continuous US trading until user stops."""
        await self._run_trading_loop("us")

    async def _set_trading_state_db(self, market: str, active: bool) -> None:
        try:
            from src.core.database import get_db_manager
            from src.data.repositories import TradingStateRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = TradingStateRepository(session)
                await repo.set_trading_active(market, active)
                if active:
                    await repo.update_heartbeat(market)
        except Exception:
            pass

    async def _update_heartbeat_db(self, market: str) -> None:
        try:
            from src.core.database import get_db_manager
            from src.data.repositories import TradingStateRepository

            db = get_db_manager()
            async with db.session() as session:
                repo = TradingStateRepository(session)
                await repo.update_heartbeat(market)
        except Exception:
            pass

    async def _run_trading_loop(self, target_market: str) -> None:
        from src.core.scheduler import TradingScheduler

        scheduler = TradingScheduler(self._settings)

        if self._settings.trading_mode == TradingMode.LIVE:
            self.log_message(
                f"[bold red]⚠ 주의: {target_market.upper()} 실거래 모드 — 실제 돈으로 거래됩니다![/]"
            )
        elif self._settings.has_kis_credentials:
            self.log_message(
                f"[bold yellow]📋 {target_market.upper()} KIS 모의투자 계좌로 실제 주문이 나갑니다[/]"
            )

        is_krx = target_market == "krx"
        if is_krx:
            self._trading_active_krx = True
        else:
            self._trading_active_us = True

        await self._set_trading_state_db(target_market, True)

        interval_minutes = self._settings.turtle.signal_check_interval_minutes
        market_label = target_market.upper()
        self.log_message(
            f"[yellow]{market_label} 트레이딩 연속 모니터링 시작 (간격: {interval_minutes}분)[/]"
        )

        cycle_count = 0
        was_market_closed = False
        trading_active = lambda: self._trading_active_krx if is_krx else self._trading_active_us

        try:
            from decimal import Decimal

            from src.core.database import get_db_manager
            from src.data.repositories import (
                CANSLIMScoreRepository,
                DailyPriceRepository,
                OrderRepository,
                PositionRepository,
                SignalRepository,
                StockRepository,
            )
            from src.execution.order_manager import OrderManager
            from src.execution.paper_broker import PaperBroker
            from src.execution.live_broker import LiveBroker
            from src.risk.position_sizing import PositionSizer
            from src.risk.unit_limits import UnitLimitManager
            from src.signals.turtle import TurtleSignalEngine
            from src.signals.breakout import BreakoutProximityWatcher, WatchedStock
            from src.signals.atr import ATRCalculator
            from src.core.trade_journal import TradeJournal

            trade_journal = TradeJournal()

            if self._settings.has_kis_credentials:
                from typing import cast
                from src.execution.live_broker import MarketType
                broker = LiveBroker(self._settings, market=cast(MarketType, target_market))
                market_suffix = "US" if target_market == "us" else "KRX"
                broker_label = (
                    f"KIS 모의투자 API ({market_suffix})" if self._settings.is_paper_mode else f"KIS 실거래 API ({market_suffix})"
                )
            else:
                broker = PaperBroker(initial_cash=Decimal("100000000"))
                broker_label = "인메모리 시뮬레이션"
            self.log_message(f"[cyan]브로커: {broker_label}[/]")
            await broker.connect()

            proximity_watcher = BreakoutProximityWatcher(self._settings.turtle)
            fast_poll_seconds = self._settings.turtle.fast_poll_interval_seconds
            self.log_message(
                f"[cyan]돌파 근접 감시: {self._settings.turtle.breakout_proximity_pct:.1%} 이내 → "
                f"{fast_poll_seconds}초 간격 폴링[/]"
            )

            while trading_active():
                # Check if market is open
                market_open = (
                    scheduler.is_krx_market_open() if is_krx else scheduler.is_us_market_open()
                )

                if not market_open:
                    if not was_market_closed:
                        next_open = scheduler.get_next_market_open(target_market)
                        next_open_str = next_open.strftime("%m/%d %H:%M") if next_open else "미정"
                        self.log_message(
                            f"[dim]{market_label} 시장 마감 중. 다음 개장: {next_open_str} — 대기 중...[/]"
                        )
                        was_market_closed = True
                    for _ in range(60):
                        if not trading_active():
                            break
                        await asyncio.sleep(1)
                    continue

                if was_market_closed:
                    self.log_message(
                        f"[green]{market_label} 시장이 개장되었습니다. 트레이딩을 재개합니다.[/]"
                    )
                    was_market_closed = False

                cycle_count += 1
                self.log_message(f"[yellow]── {market_label} 트레이딩 사이클 #{cycle_count} ──[/]")

                try:
                    db = get_db_manager()
                    async with db.session() as session:
                        price_repo = DailyPriceRepository(session)
                        position_repo = PositionRepository(session)
                        signal_repo = SignalRepository(session)
                        order_repo = OrderRepository(session)
                        stock_repo = StockRepository(session)

                        signal_engine = TurtleSignalEngine(
                            price_repo=price_repo,
                            position_repo=position_repo,
                            signal_repo=signal_repo,
                            stock_repo=stock_repo,
                        )

                        position_sizer = PositionSizer(self._settings.risk)
                        unit_manager = UnitLimitManager(self._settings.risk, position_repo)
                        order_manager = OrderManager(
                            broker=broker,
                            position_sizer=position_sizer,
                            unit_manager=unit_manager,
                            order_repo=order_repo,
                            position_repo=position_repo,
                            trade_journal=trade_journal,
                            stock_name="",
                            stock_market=target_market,
                        )

                        async def fetch_realtime_prices(stock_ids: list[int], batch_size: int = 20) -> dict[int, Decimal]:
                            prices: dict[int, Decimal] = {}
                            
                            async def fetch_single(sid: int) -> tuple[int, Decimal | None]:
                                try:
                                    stock = await stock_repo.get_by_id(sid)
                                    if stock:
                                        price = await broker.get_current_price(stock.symbol)
                                        if price and price > 0:
                                            return (sid, price)
                                except Exception:
                                    pass
                                return (sid, None)
                            
                            for i in range(0, len(stock_ids), batch_size):
                                batch = stock_ids[i:i + batch_size]
                                results = await asyncio.gather(*[fetch_single(sid) for sid in batch])
                                for sid, price in results:
                                    if price is not None:
                                        prices[sid] = price
                            
                            return prices

                        open_positions = await position_repo.get_open_positions()
                        position_stock_ids = [p.stock_id for p in open_positions]
                        position_prices = await fetch_realtime_prices(position_stock_ids) if position_stock_ids else {}

                        exit_signals = await signal_engine.check_exit_signals(realtime_prices=position_prices)
                        self.log_message(
                            f"[bold]{market_label} 청산 시그널: {len(exit_signals)}개[/]"
                        )
                        for sig in exit_signals:
                            exit_type = "손절" if sig.signal_type == "STOP_LOSS" else "채널청산"
                            name_info = f" {sig.name}" if sig.name else ""
                            self.log_message(
                                f"  [red]▼ {exit_type}[/] {sig.symbol}{name_info} | "
                                f"현재가 {sig.price:,.0f} | "
                                f"유형 {sig.signal_type} S{sig.system}"
                            )
                            result = await order_manager.execute_exit(sig)
                            if result.success and result.filled_price:
                                self.log_message(
                                    f"    [green]✓ 체결[/] {result.quantity}주 × {result.filled_price:,.0f}원"
                                )
                            else:
                                self.log_message(f"    [red]✗ 실패[/] {result.message}")

                        pyramid_signals = await signal_engine.check_pyramid_signals(realtime_prices=position_prices)
                        self.log_message(
                            f"[bold]{market_label} 피라미딩 시그널: {len(pyramid_signals)}개[/]"
                        )
                        for sig in pyramid_signals:
                            stop_info = f" | 손절가 {sig.stop_loss:,.0f}" if sig.stop_loss else ""
                            name_info = f" {sig.name}" if sig.name else ""
                            self.log_message(
                                f"  [cyan]△ 피라미딩[/] {sig.symbol}{name_info} | "
                                f"현재가 {sig.price:,.0f}{stop_info}"
                            )
                            result = await order_manager.execute_pyramid(sig)
                            if result.success and result.filled_price:
                                self.log_message(
                                    f"    [green]✓ 체결[/] {result.quantity}주 × {result.filled_price:,.0f}원"
                                )
                            else:
                                self.log_message(f"    [yellow]⊘ 스킵[/] {result.message}")

                        scores = await CANSLIMScoreRepository(session).get_candidates(
                            min_score=5, market=target_market
                        )
                        candidate_ids = [s.stock_id for s in scores]
                        self.log_message(
                            f"[bold]{market_label} CANSLIM 후보: {len(candidate_ids)}개[/]"
                        )

                        candidate_prices = await fetch_realtime_prices(candidate_ids) if candidate_ids else {}
                        entry_signals = await signal_engine.check_entry_signals_realtime(candidate_ids, candidate_prices)
                        self.log_message(
                            f"[bold]{market_label} 진입 시그널: {len(entry_signals)}개[/]"
                        )
                        for sig in entry_signals:
                            system_label = "20일돌파" if sig.system == 1 else "55일돌파"
                            breakout_info = (
                                f" | 돌파가 {sig.breakout_level:,.0f}" if sig.breakout_level else ""
                            )
                            name_info = f" {sig.name}" if sig.name else ""
                            self.log_message(
                                f"  [green]▲ 진입[/] {sig.symbol}{name_info} | "
                                f"현재가 [bold]{sig.price:,.0f}[/]{breakout_info} | "
                                f"ATR {sig.atr_n:,.0f} | "
                                f"{system_label} ({sig.signal_type})"
                            )
                            result = await order_manager.execute_entry(sig)
                            if result.success and result.filled_price:
                                total_cost = result.quantity * result.filled_price
                                self.log_message(
                                    f"    [green]✓ 체결[/] {result.quantity}주 × {result.filled_price:,.0f}원 "
                                    f"(총 {total_cost:,.0f}원)"
                                )
                            else:
                                self.log_message(f"    [yellow]⊘ 스킵[/] {result.message}")

                        proximity_watcher.clear()
                        atr_calc = ATRCalculator(self._settings.turtle)
                        for cid in candidate_ids:
                            existing_pos = await position_repo.get_by_stock(cid, open_only=True)
                            if existing_pos:
                                continue
                            prices = await price_repo.get_period(cid, 60)
                            if len(prices) < 56:
                                continue
                            highs = [p.high for p in prices]
                            lows = [p.low for p in prices]
                            closes = [p.close for p in prices]
                            current_close = candidate_prices.get(cid, closes[-1])
                            atr_result = atr_calc.calculate(highs, lows, closes)
                            if not atr_result:
                                continue
                            detector = signal_engine._breakout
                            targets = detector.check_proximity(
                                current_close,
                                highs,
                                Decimal(str(self._settings.turtle.breakout_proximity_pct)),
                            )
                            if targets:
                                stock_info = await signal_engine._get_stock_info(cid)
                                symbol = stock_info["symbol"] if stock_info else str(cid)
                                name = stock_info["name"] if stock_info else ""
                                proximity_watcher.register(
                                    WatchedStock(
                                        stock_id=cid,
                                        symbol=symbol,
                                        name=name,
                                        targets=targets,
                                        highs=highs,
                                        lows=lows,
                                        closes=closes,
                                        atr_n=atr_result.atr,
                                    )
                                )

                        if proximity_watcher.has_targets:
                            symbols_str = ", ".join(proximity_watcher.watched_symbols)
                            self.log_message(
                                f"[magenta]⚡ 돌파 근접 감시 대상: {proximity_watcher.watched_count}개 "
                                f"({symbols_str}) → {fast_poll_seconds}초 간격 폴링[/]"
                            )

                    await self._load_signals()
                    await self._load_portfolio()
                    await self._update_heartbeat_db(target_market)
                    self._update_status()

                    self.log_message(
                        f"[dim]{market_label} 사이클 #{cycle_count} 완료. 다음 사이클까지 {interval_minutes}분 대기...[/]"
                    )

                except Exception as e:
                    self.log_message(f"[red]{market_label} 트레이딩 사이클 오류: {e}[/]")

                elapsed = 0
                total_wait = interval_minutes * 60
                while elapsed < total_wait and trading_active():
                    if proximity_watcher.has_targets:
                        try:
                            db = get_db_manager()
                            async with db.session() as poll_session:
                                poll_order_repo = OrderRepository(poll_session)
                                poll_position_repo = PositionRepository(poll_session)
                                poll_signal_repo = SignalRepository(poll_session)
                                poll_stock_repo = StockRepository(poll_session)

                                poll_position_sizer = PositionSizer(self._settings.risk)
                                poll_unit_manager = UnitLimitManager(
                                    self._settings.risk, poll_position_repo
                                )
                                poll_order_manager = OrderManager(
                                    broker=broker,
                                    position_sizer=poll_position_sizer,
                                    unit_manager=poll_unit_manager,
                                    order_repo=poll_order_repo,
                                    position_repo=poll_position_repo,
                                    trade_journal=trade_journal,
                                    stock_name="",
                                    stock_market=target_market,
                                )

                                for watched in proximity_watcher.get_watched_list():
                                    try:
                                        price = await broker.get_current_price(watched.symbol)
                                        if price <= 0:
                                            continue

                                        breakout = proximity_watcher.check_breakout(
                                            watched.stock_id, price
                                        )
                                        if breakout and breakout.is_entry:
                                            from src.signals.turtle import TurtleSignal

                                            signal = TurtleSignal(
                                                symbol=watched.symbol,
                                                stock_id=watched.stock_id,
                                                signal_type=breakout.breakout_type.value,
                                                system=breakout.system,
                                                price=price,
                                                atr_n=watched.atr_n,
                                                stop_loss=price - (watched.atr_n * Decimal("2")),
                                                position_size=None,
                                                timestamp=datetime.now(),
                                                breakout_level=breakout.breakout_level,
                                                name=watched.name,
                                            )

                                            await poll_signal_repo.create(
                                                stock_id=signal.stock_id,
                                                timestamp=signal.timestamp,
                                                signal_type=signal.signal_type,
                                                price=signal.price,
                                                system=signal.system,
                                                atr_n=signal.atr_n,
                                            )

                                            system_label = (
                                                "20일돌파" if signal.system == 1 else "55일돌파"
                                            )
                                            self.log_message(
                                                f"  [green bold]⚡ 돌파 감지![/] {signal.symbol}"
                                                f" {watched.name} | "
                                                f"현재가 [bold]{price:,.0f}[/] | "
                                                f"돌파가 {breakout.breakout_level:,.0f} | "
                                                f"{system_label}"
                                            )

                                            result = await poll_order_manager.execute_entry(signal)
                                            if result.success and result.filled_price:
                                                total_cost = result.quantity * result.filled_price
                                                self.log_message(
                                                    f"    [green]✓ 체결[/] {result.quantity}주 × "
                                                    f"{result.filled_price:,.0f}원 "
                                                    f"(총 {total_cost:,.0f}원)"
                                                )
                                            else:
                                                self.log_message(
                                                    f"    [yellow]⊘ 스킵[/] {result.message}"
                                                )
                                    except Exception as e:
                                        self.log_message(
                                            f"    [red]폴링 오류[/] {watched.symbol}: {e}"
                                        )

                        except Exception as e:
                            self.log_message(f"[red]Fast poll 오류: {e}[/]")

                        await asyncio.sleep(fast_poll_seconds)
                        elapsed += fast_poll_seconds
                    else:
                        await asyncio.sleep(1)
                        elapsed += 1

            await broker.disconnect()

            self.log_message(
                f"[green]{market_label} 트레이딩 종료 (총 {cycle_count}회 사이클 실행)[/]"
            )

        except Exception as e:
            self.log_message(f"[red]{market_label} 트레이딩 오류: {e}[/]")

        finally:
            await self._set_trading_state_db(target_market, False)
            if is_krx:
                self._trading_active_krx = False
            else:
                self._trading_active_us = False
            self.log_message(f"[green]{target_market.upper()} 트레이딩 종료[/]")

    def action_stop_trading_krx(self) -> None:
        if self._trading_active_krx:
            self._trading_active_krx = False
            self.log_message(
                "[yellow]KRX 트레이딩 중지 요청됨. 현재 사이클 완료 후 종료됩니다...[/]"
            )

    def action_stop_trading_us(self) -> None:
        """Stop the US trading loop."""
        if self._trading_active_us:
            self._trading_active_us = False
            self.log_message(
                "[yellow]US 트레이딩 중지 요청됨. 현재 사이클 완료 후 종료됩니다...[/]"
            )

    def action_toggle_trading_krx(self) -> None:
        """Toggle KRX trading on/off."""
        if self._trading_active_krx:
            self.action_stop_trading_krx()
        else:
            self.action_run_trading_krx()

    def action_toggle_trading_us(self) -> None:
        """Toggle US trading on/off."""
        if self._trading_active_us:
            self.action_stop_trading_us()
        else:
            self.action_run_trading_us()


def run_tui() -> None:
    """Run the TUI application."""
    app = TurtleCANSLIMApp()
    app.run()


if __name__ == "__main__":
    run_tui()
