from typing import List, Dict, Optional, Callable, Any, Union

class Round:
    def __init__(
        self,
        round_id: str,
        question: str,
        options: List[str],
        open_lap: int,
        close_lap: int,
        evaluator: Callable[[Dict[str, Any], int], Optional[Union[str, List[str]]]],
        explanation_builder: Callable[[Dict[str, Any]], str],
        settle_at_finish: bool = False
    ):
        self.id = round_id
        self.question = question
        self.options = options
        self.open_lap = open_lap
        self.close_lap = close_lap
        self.evaluator = evaluator
        self.explanation_builder = explanation_builder
        self.settle_at_finish = settle_at_finish
        self.status = "pending"  # pending, open, closed, settled, cancelled
        self.winner: Optional[List[str]] = None
        self.explanation: str = ""

    def check_validity(self, race_data: Dict[str, Any]) -> bool:
        # Never open if SC/VSC/red flag occurs in the voting window [open_lap, close_lap]
        for l in range(self.open_lap, self.close_lap + 1):
            events = race_data["laps"].get(str(l), {}).get("events", [])
            for e in events:
                if e.get("type") in ("safety_car_deployed", "vsc_deployed", "red_flag"):
                    return False
        return True

    def check(self, current_lap: int, race_data: Dict[str, Any], is_lap_end: bool = False) -> Optional[str]:
        # Opening and closing can occur at start of lap
        if not is_lap_end:
            if self.status == "pending" and current_lap >= self.open_lap:
                if not self.check_validity(race_data):
                    self.status = "cancelled"
                    return None
                self.status = "open"
                return "opened"
            if self.status == "open" and current_lap >= self.close_lap:
                self.status = "closed"
                return "closed"
            return None

        # Settlement occurs STRICTLY at the end of the lap after events are sent
        if self.status == "closed":
            total_laps = race_data["race_info"]["total_laps"]
            if self.settle_at_finish and current_lap < total_laps:
                return None

            result = self.evaluator(race_data, current_lap)
            if result is not None:
                if isinstance(result, str):
                    self.winner = [result]
                else:
                    self.winner = result
                self.explanation = self.explanation_builder(race_data)
                self.status = "settled"
                return "settled"
        return None

def build_f1_rounds(race_data: Dict[str, Any]) -> List[Round]:
    rounds = []

    # Round 1: Who pits next? (Open lap 5, close lap 9)
    candidates_r1 = ["LEC", "RUS", "NOR", "HAM"]
    def eval_r1(data: Dict, lap: int) -> Optional[str]:
        events = data["laps"].get(str(lap), {}).get("events", [])
        for e in events:
            if e.get("type") == "pit" and e.get("driver") in candidates_r1:
                return e["driver"]
        return None

    rounds.append(Round(
        round_id="r1",
        question="Who pits next?",
        options=candidates_r1,
        open_lap=5,
        close_lap=9,
        evaluator=eval_r1,
        explanation_builder=lambda d: "Charles Leclerc pitted on lap 24."
    ))

    # Round 2: Safety car before lap 35? (Open 15, close 19)
    def eval_r2(data: Dict, lap: int) -> Optional[str]:
        events = data["laps"].get(str(lap), {}).get("events", [])
        for e in events:
            if e.get("type") in ("safety_car_deployed", "vsc_deployed"):
                return "Yes"
        if lap == 35:
            return "No"
        return None

    rounds.append(Round(
        round_id="r2",
        question="Safety car before lap 35?",
        options=["Yes", "No"],
        open_lap=15,
        close_lap=19,
        evaluator=eval_r2,
        explanation_builder=lambda d: "Virtual Safety Car deployed on lap 28."
    ))

    # Round 3: Safety car before lap 45? (Open 34, close 38 - green flag window)
    def eval_r3(data: Dict, lap: int) -> Optional[str]:
        events = data["laps"].get(str(lap), {}).get("events", [])
        for e in events:
            if e.get("type") == "safety_car_deployed":
                return "Yes"
        if lap == 45:
            return "No"
        return None

    rounds.append(Round(
        round_id="r3",
        question="Safety car before lap 45?",
        options=["Yes", "No"],
        open_lap=34,
        close_lap=38,
        evaluator=eval_r3,
        explanation_builder=lambda d: "Safety Car deployed on lap 39."
    ))

    # Round 4: Who gains most places from lap 49 to 59? (Open 45, close 49)
    # Exclude top 3 at lap 45 (VER, OCO, GAS). Use midfield: RUS, LEC, HAM, NOR
    candidates_r4 = ["RUS", "LEC", "HAM", "NOR"]
    def eval_r4(data: Dict, lap: int) -> Optional[List[str]]:
        if lap < 59:
            return None
        p_start = data["laps"].get("49", {}).get("positions", {})
        p_end = data["laps"].get("59", {}).get("positions", {})
        gains = {}
        for c in candidates_r4:
            if c in p_start and c in p_end:
                gains[c] = p_start[c] - p_end[c]
        if not gains:
            return ["None"]
        max_gain = max(gains.values())
        if max_gain <= 0:
            return ["None"]
        # Allow ties: all tied pickers score
        winners = [c for c, g in gains.items() if g == max_gain]
        return winners

    rounds.append(Round(
        round_id="r4",
        question="Who gains the most places from lap 49 to 59?",
        options=candidates_r4,
        open_lap=45,
        close_lap=49,
        evaluator=eval_r4,
        explanation_builder=lambda d: "Lewis Hamilton gained 1 place by lap 59."
    ))

    # Round 5: Another safety car before the finish? (Open 52, close 56)
    # Settle strictly at race finish (lap 69)
    def eval_r5(data: Dict, lap: int) -> Optional[str]:
        total = data["race_info"]["total_laps"]
        if lap < total:
            return None
        for l in range(57, total + 1):
            events = data["laps"].get(str(l), {}).get("events", [])
            for e in events:
                if e.get("type") in ("safety_car_deployed", "vsc_deployed"):
                    return "Yes"
        return "No"

    rounds.append(Round(
        round_id="r5",
        question="Another safety car before the finish?",
        options=["Yes", "No"],
        open_lap=52,
        close_lap=56,
        evaluator=eval_r5,
        explanation_builder=lambda d: "No safety car was deployed after lap 56.",
        settle_at_finish=True
    ))

    return rounds
