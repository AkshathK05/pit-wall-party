import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from rounds import Round, build_f1_rounds
from writer import (
    format_lap_message,
    format_final_results,
    format_leaderboard,
    generate_ai_commentary,
    generate_ai_round_banter,
    to_surname,
    event_priority
)
import db

logger = logging.getLogger("pitwall.replay")

active_replays: Dict[str, "ReplaySession"] = {}

class ReplaySession:
    def __init__(
        self,
        chat_id: str,
        race_data: Dict[str, Any],
        seconds_per_lap: float,
        send_message_cb: Callable,
        close_round_cb: Optional[Callable] = None,
        use_ai: bool = False,
        from_lap: int = 1,
        to_lap: Optional[int] = None
    ):
        self.chat_id = str(chat_id)
        self.race_data = race_data
        self.seconds_per_lap = seconds_per_lap
        self.send_message_cb = send_message_cb
        self.close_round_cb = close_round_cb
        self.use_ai = use_ai
        self.from_lap = from_lap
        self.to_lap = to_lap or race_data["race_info"]["total_laps"]
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.current_lap = 0
        # Skip any round whose open lap is before from_lap
        self.rounds: List[Round] = [
            r for r in build_f1_rounds(race_data)
            if r.open_lap >= self.from_lap
        ]

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        active_replays[self.chat_id] = self
        self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
        active_replays.pop(self.chat_id, None)

    async def _emit(self, text: str, buttons: Optional[List[str]] = None, round_id: Optional[str] = None) -> None:
        try:
            res = self.send_message_cb(self.chat_id, text, buttons=buttons, round_id=round_id)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.error("Error sending replay message: %s", e)

    async def _run(self) -> None:
        total_laps = self.race_data["race_info"]["total_laps"]
        race_name = self.race_data["race_info"]["name"]
        year = self.race_data["race_info"]["year"]

        start_info = f"Starting replay: {year} {race_name} (Laps {self.from_lap}-{self.to_lap} of {total_laps})."
        await self._emit(start_info)

        try:
            for lap in range(self.from_lap, self.to_lap + 1):
                if not self.running:
                    break
                self.current_lap = lap

                # 1. Round lifecycle: Open & Close check at start of lap
                for r in self.rounds:
                    action = r.check(lap, self.race_data, is_lap_end=False)
                    if action == "opened":
                        msg = f"Prediction Round: {r.question}\nTap your pick below. Voting open for 4 laps."
                        await self._emit(msg, buttons=r.options, round_id=r.id)
                    elif action == "closed":
                        if self.close_round_cb:
                            res = self.close_round_cb(self.chat_id, r.id)
                            if asyncio.iscoroutine(res):
                                await res
                        await self._emit(f"Voting closed for: \"{r.question}\". Outcome locked in.")

                # 2. Process lap events
                lap_str = str(lap)
                lap_info = self.race_data["laps"].get(lap_str, {})
                raw_events = list(lap_info.get("events", []))
                # Sort events by priority: red flag, SC/VSC, lead change, penalty, overtakes, pits
                events = sorted(raw_events, key=event_priority)

                # Lead changes get their own message sent first
                lead_changes = [
                    e for e in events
                    if e.get("type") == "overtake" and e.get("new_position") == 1
                ]
                remaining_events = [
                    e for e in events
                    if not (e.get("type") == "overtake" and e.get("new_position") == 1)
                ]

                for lc in lead_changes:
                    d = to_surname(lc.get("driver", "Driver"))
                    p = to_surname(lc.get("passed", "car"))
                    grid = lc.get("starting_grid", 1)
                    lc_ai = None
                    if self.use_ai:
                        lc_ai = await generate_ai_commentary([lc])
                    msg = lc_ai if lc_ai else f"Lead change: {d} gets past {p} to take P1 (started P{grid})."
                    await self._emit(msg)

                # Use AI only for: SC/VSC/red flag, penalties, laps with 3+ events
                should_use_ai = self.use_ai and (
                    any(e.get("type") in ("safety_car_deployed", "vsc_deployed", "red_flag") for e in remaining_events) or
                    any(e.get("type") == "penalty" for e in remaining_events) or
                    len(remaining_events) >= 3
                )

                ai_text = None
                if should_use_ai and remaining_events:
                    try:
                        ai_text = await generate_ai_commentary(remaining_events)
                    except Exception as e:
                        logger.warning("Error generating AI commentary: %s", e)

                show_header = (lap == 1 or lap % 5 == 0 or lap == total_laps)
                lap_msg = format_lap_message(
                    lap=lap,
                    total_laps=total_laps,
                    events=remaining_events,
                    show_header=show_header,
                    ai_text=ai_text
                )

                if lap_msg:
                    await self._emit(lap_msg)

                # 3. Round Settlement: Strictly AFTER lap events have been emitted
                for r in self.rounds:
                    settled = r.check(lap, self.race_data, is_lap_end=True)
                    if settled == "settled":
                        winners = r.winner or []
                        votes = db.get_votes(self.chat_id, r.id)
                        scored_users = []
                        zero_users = []
                        for uid, uname, choice in votes:
                            if choice in winners:
                                db.add_points(self.chat_id, uid, uname, 10)
                                scored_users.append(uname)
                            else:
                                zero_users.append(uname)

                        winners_str = ", ".join(to_surname(w) for w in winners)
                        fan_line = f"10 pts to: {', '.join(scored_users)}." if scored_users else "Nobody scored this round."

                        # The result line is ALWAYS the template
                        template_result = f"Result: {r.question}\nWinner: {winners_str}. {r.explanation}\n{fan_line}"

                        # AI writes only one banter line after it (if AI fails, no banter line)
                        banter_line = None
                        if self.use_ai:
                            try:
                                lb_current = db.get_leaderboard(self.chat_id)
                                leader_name = lb_current[0]["name"] if lb_current else "Arjun"
                                banter_line = await generate_ai_round_banter(
                                    question=r.question,
                                    correct_answer=winners_str,
                                    winner_names=scored_users,
                                    loser_names=zero_users,
                                    current_leader=leader_name
                                )
                            except Exception as e:
                                logger.warning("Error generating AI round banter: %s", e)

                        if banter_line:
                            settle_msg = f"{template_result}\n\n{banter_line}"
                        else:
                            settle_msg = template_result

                        await self._emit(settle_msg)

                        # Skip posting leaderboard when everyone has 0
                        lb = db.get_leaderboard(self.chat_id)
                        if lb and any(s["score"] > 0 for s in lb):
                            await self._emit(format_leaderboard(lb))

                # Lap delay
                await asyncio.sleep(self.seconds_per_lap)

            # Replay complete
            if self.running and self.to_lap == total_laps:
                last_lap_str = str(total_laps)
                final_pos = self.race_data["laps"].get(last_lap_str, {}).get("positions", {})
                sorted_finish = sorted(final_pos.items(), key=lambda x: x[1])
                top3 = [code for code, _ in sorted_finish[:3]]
                lb = db.get_leaderboard(self.chat_id)
                final_summary = format_final_results(top3, lb)
                await self._emit(final_summary)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Replay encountered error on lap %d: %s", self.current_lap, e)
        finally:
            self.running = False
            active_replays.pop(self.chat_id, None)
