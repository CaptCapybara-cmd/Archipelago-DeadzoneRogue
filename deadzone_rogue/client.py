"""Deadzone Rogue client: connects to the Archipelago server and talks to the APClient Lua mod through files
(see bridge.py)."""
import asyncio
import copy
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import Utils
from CommonClient import (ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg, logger,
                          server_loop)
from NetUtils import ClientStatus

from . import bridge

POLL_SECONDS = 1.0
HEARTBEAT_TIMEOUT = 15


class DeadzoneRogueCommandProcessor(ClientCommandProcessor):
    def _cmd_game(self) -> None:
        """Show whether the game (APClient mod) is talking to this client."""
        if isinstance(self.ctx, DeadzoneRogueContext):
            logger.info(self.ctx.game_status())

    def _cmd_goal(self) -> None:
        """Show which missions are still needed for the goal."""
        if isinstance(self.ctx, DeadzoneRogueContext):
            names = {m["key"]: m["name"] for m in self.ctx.data["missions"]}
            needed = [k for k in self.ctx.slot_data.get("goal_missions", []) if k not in self.ctx.completed_missions]
            total = len(self.ctx.slot_data.get("goal_missions", []))
            logger.info(f"Goal: {total - len(needed)}/{total} missions completed.")
            if needed:
                logger.info("Still needed: " + ", ".join(names.get(k, k) for k in needed))

    def _cmd_gamedir(self, path: str = "") -> None:
        """Show or set the game's Win64 folder (where DeadzoneSteam-Win64-Shipping.exe is)."""
        if isinstance(self.ctx, DeadzoneRogueContext):
            if path:
                self.ctx.set_game_dir(path)
            logger.info(f"Game folder: {self.ctx.game_dir}")


class DeadzoneRogueContext(CommonContext):
    command_processor = DeadzoneRogueCommandProcessor
    game = "Deadzone Rogue"
    items_handling = 0b111  # all items, including our own and the starting kit

    def __init__(self, server_address: Optional[str], password: Optional[str], game_dir: str) -> None:
        super().__init__(server_address, password)
        self.data = bridge.load_data()
        self.slot_data: Dict[str, Any] = {}
        self.inbox_rev = 0
        self.outbox_offset = 0
        self.started_at = time.time()
        self.goal_sent = False
        self.session = ""
        self.notes: List[Tuple[int, str]] = []  # (id, text) for in-game chat; ids are millisecond timestamps
        self.deathlinks: List[Tuple[int, str, str]] = []  # (id, mode, source) received, for the mod to apply
        self.last_deathlink_received = 0.0
        self.inbox_pending = False  # the last inbox write failed; retried by the game loop
        self.completed_missions: Set[str] = set()  # rebuilt from this session's outbox, which is read from the start
        self.set_game_dir(game_dir)

    def set_game_dir(self, game_dir: str) -> None:
        self.game_dir = game_dir
        self.bridge_dir = os.path.join(game_dir, bridge.BRIDGE_DIR)
        if os.path.isdir(game_dir):
            os.makedirs(self.bridge_dir, exist_ok=True)
        else:
            logger.warning(f"Game folder not found: {game_dir}. Set it with /gamedir <path>.")
        self.outbox_offset = 0

    def game_status(self) -> str:
        try:
            with open(os.path.join(self.bridge_dir, "heartbeat.txt")) as f:
                age = time.time() - float(f.readline().strip() or 0)  # line 1: unix time; the rest is for the launcher
        except (OSError, ValueError):
            return "Game: no heartbeat yet (is the APClient mod enabled and the game running?)"
        if age > HEARTBEAT_TIMEOUT:
            return f"Game: last heard from {int(age)} s ago (game closed or mod not running)"
        return "Game: connected"

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", {})
            self.goal_sent = False
            self.write_inbox()
            asyncio.create_task(self.update_death_link(bool(self.slot_data.get("death_link"))))
        elif cmd == "ReceivedItems":
            self.write_inbox()

    MAX_NOTES = 30

    @staticmethod
    def next_id(entries: list) -> int:
        """Millisecond timestamp, kept increasing (the mod applies each id once)."""
        return max(int(time.time() * 1000), (entries[-1][0] + 1) if entries else 0)

    def add_note(self, text: str) -> None:
        note_id = self.next_id(self.notes)
        self.notes = (self.notes + [(note_id, text[:150])])[-self.MAX_NOTES:]
        self.write_inbox()

    def on_print_json(self, args: dict) -> None:
        super().on_print_json(args)
        # Item messages that involve this player are repeated in the game's chat.
        if args.get("type") in ("ItemSend", "ItemCheat") and self.slot is not None:
            item = args.get("item")
            sender = item.get("player") if isinstance(item, dict) else getattr(item, "player", None)
            if args.get("receiving") == self.slot or sender == self.slot:
                self.add_note(self.rawjsontotextparser(copy.deepcopy(args["data"])))

    def on_deathlink(self, data: Dict[str, Any]) -> None:
        super().on_deathlink(data)
        self.last_deathlink_received = time.time()
        mode = self.slot_data.get("death_link_mode", "lose_perk")
        source = data.get("source", "another player")
        self.deathlinks = (self.deathlinks + [(self.next_id(self.deathlinks), mode, source)])[-self.MAX_NOTES:]
        self.write_inbox()

    def write_inbox(self) -> None:
        if not self.slot_data or not os.path.isdir(self.bridge_dir):
            return
        self.inbox_rev += 1
        session = bridge.session_id(self.server_seed_name or self.seed_name or "seed", self.auth or "slot")
        if session != self.session:  # new AP session: read its outbox from the start
            self.session, self.outbox_offset, self.completed_missions = session, 0, set()
        received = [item.item for item in self.items_received]
        grants = bridge.grant_lines(self.data, self.slot_data, received)
        text = bridge.render_inbox(self.inbox_rev, session, self.slot_data,
                                   bridge.lock_paths(self.data, self.slot_data), grants,
                                   bridge.gating_lines(self.data, self.slot_data, received), self.notes,
                                   self.deathlinks)
        try:
            bridge.write_atomic(os.path.join(self.bridge_dir, "inbox.txt"), text)
            self.inbox_pending = False
        except OSError as e:  # never let a locked file take the server connection down with it
            self.inbox_pending = True
            logger.debug(f"inbox write failed, retrying shortly: {e}")

    async def poll_game(self) -> None:
        path = os.path.join(self.bridge_dir, f"outbox_{self.session}.txt")
        if not self.slot_data or not self.session or not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            f.seek(self.outbox_offset)
            text = f.read()
            self.outbox_offset = f.tell()
        if not text:
            return
        events = bridge.parse_outbox(text)
        locations, completed, deaths = bridge.checks_from_events(self.data, self.slot_data, events, self.started_at)
        self.completed_missions |= completed
        new = locations - self.checked_locations
        if new:
            await self.check_locations(new)
        if (bridge.goal_complete(self.slot_data, self.completed_missions)
                and not self.goal_sent and not self.finished_game):
            await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
            self.goal_sent = True
            logger.info("Goal complete!")
            self.add_note("Goal complete! Every goal mission is done.")
        # a death right after a received DeathLink is that DeathLink's doing (the kill mode), not a new one
        if deaths and "DeathLink" in self.tags and time.time() - self.last_deathlink_received > 15:
            await self.send_death(f"{self.player_names.get(self.slot, 'A Deadzone Rogue player')} died on the station.")

    async def game_loop(self) -> None:
        while not self.exit_event.is_set():
            try:
                if self.inbox_pending:
                    self.write_inbox()
                await self.poll_game()
            except Exception as e:  # keep the loop alive; a half-written line is retried next tick
                logger.debug(f"poll_game: {e}")
            await asyncio.sleep(POLL_SECONDS)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Deadzone Rogue Client"
        return ui


def launch(*launch_args: str) -> None:
    async def main() -> None:
        parser = get_base_parser(description="Deadzone Rogue Archipelago client.")
        parser.add_argument("--game-dir", default=bridge.DEFAULT_GAME_DIR,
                            help="The game's Valhalla/Binaries/Win64 folder.")
        parser.add_argument("--name", default=None, help="Slot name to connect as.")
        parser.add_argument("url", nargs="?", help="Archipelago connection url")
        args = handle_url_arg(parser.parse_args(launch_args), parser=parser)
        ctx = DeadzoneRogueContext(args.connect, args.password, args.game_dir)
        ctx.auth = args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
        game_task = asyncio.create_task(ctx.game_loop(), name="GameLoop")
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await ctx.exit_event.wait()
        ctx.server_address = None
        await ctx.shutdown()
        await game_task

    Utils.init_logging("DeadzoneRogueClient")
    import colorama
    colorama.just_fix_windows_console()
    asyncio.run(main())
    colorama.deinit()
