# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long
from typing import List, Dict, Tuple, Set
import random, time, logging
from agari_judge import AgariJudger, HandResponse, get_tenpai_tiles
from debug_setting import debug_yama, debug_cards
logger = logging.getLogger("uvicorn")

WAITING, RUNNING, RECONNECT, ENDED = 0, 1, 2, 3


# ---------------------------------------------------------------------------
# Riichi kan legality helpers
# ---------------------------------------------------------------------------

def _find_exactly_n_mentsu(counts: List[int], n: int) -> List[List]:
    """Recursively find all ways to partition tile counts into exactly n mentsu.
    counts: 9-element list of tile counts for 1s-9s (0-indexed).
    Returns list of decompositions; each decomposition is a list of ('koutsu'|'shuntsu', start_idx).
    """
    if n == 0:
        return [[]] if all(c == 0 for c in counts) else []
    pos = next((i for i in range(9) if counts[i] > 0), None)
    if pos is None:
        return []
    results = []
    if counts[pos] >= 3:
        nc = list(counts)
        nc[pos] -= 3
        for rest in _find_exactly_n_mentsu(nc, n - 1):
            results.append([('koutsu', pos)] + rest)
    if pos + 2 < 9 and counts[pos + 1] >= 1 and counts[pos + 2] >= 1:
        nc = list(counts)
        nc[pos] -= 1; nc[pos + 1] -= 1; nc[pos + 2] -= 1
        for rest in _find_exactly_n_mentsu(nc, n - 1):
            results.append([('shuntsu', pos)] + rest)
    return results


def _kan_tile_in_shuntsu(hand: List[str], kan_card: str) -> bool:
    """Return True if kan_card appears in a shuntsu in ANY valid tenpai decomposition of hand."""
    kan_val = int(kan_card[0]) - 1
    tenpai_tiles = get_tenpai_tiles(hand)
    if not tenpai_tiles:
        return False
    needed_mentsu = (len(hand) - 1) // 3  # 13→4, 10→3, 7→2
    for win_tile in tenpai_tiles:
        hand_complete = hand + [win_tile]
        counts = [0] * 9
        for c in hand_complete:
            counts[int(c[0]) - 1] += 1
        for pair_pos in range(9):
            if counts[pair_pos] < 2:
                continue
            nc = list(counts)
            nc[pair_pos] -= 2
            for decomp in _find_exactly_n_mentsu(nc, needed_mentsu):
                for mtype, start in decomp:
                    if mtype == 'shuntsu' and start <= kan_val <= start + 2:
                        return True
    return False


def _is_riichi_kan_legal(player, kan_card: str) -> bool:
    """Check all three legality conditions for a riichi ankan.
    Rule 1 (source): always satisfied — only ankan exists in this game.
    Rule 2 (machi unchanged): tenpai tiles before and after kan must be identical.
    Rule 3 (structure unchanged): the 4 tiles must not appear in any shuntsu.
    """
    riichi_hand = player.hand[:-1]  # hand before current draw
    remaining = [c for c in riichi_hand if c != kan_card]
    if set(get_tenpai_tiles(remaining)) != player.riichi_machi:
        return False
    if _kan_tile_in_shuntsu(riichi_hand, kan_card):
        return False
    return True
default_rules = {
    "initial_point" : 150_000,
    "no_agari_punishment": 20_000, 
    "sort_hand" : False,
    "yaku_rules": {
        "has_daisharin" : False,
        "renhou_as_yakuman" : False,
    }
}


class ChinitsuPlayer:
    def __init__(self, name, initial_point: int, active=True) -> None:
        self.name = name
        self.active = active
        self.point = initial_point
        self.is_oya = False
        self.is_riichi = False
        self.is_daburu_riichi = False
        self.riichi_turn = None
        self.is_ippatsu = False
        self.is_rinshan = False
        self.is_furiten = False       # permanent furiten (riichi + skipped ron)
        self.is_temp_furiten = False  # temporary furiten (skipped ron, cleared on next discard)
        self.has_illegal_kan = False  # deferred penalty: illegal riichi kan
        self.riichi_machi: Set[str] = set()  # tenpai tiles saved at riichi declaration

        # last card of hand is tsumo card (only after drawing a card)
        self.hand: List[str] = []
        self.fuuro: List[Tuple[str]] = []
        self.kawa: List[Tuple[str, bool]]= []
        self.num_kan = 0


    def reset_game(self):
        self.is_oya = False
        self.is_riichi = False
        self.is_daburu_riichi = False
        self.riichi_turn = None
        self.is_ippatsu = False
        self.is_rinshan = False
        self.is_furiten = False
        self.is_temp_furiten = False
        self.has_illegal_kan = False
        self.riichi_machi: Set[str] = set()

        # last card of hand is tsumo card (only after drawing a card)
        self.hand: List[str] = []
        self.fuuro: List[Tuple[str]] = []
        self.kawa: List[Tuple[str, bool]]= []
        self.num_kan = 0

    @property
    def len_hand(self):
        return len(self.hand)

    @property
    def num_fuuro(self): # 副露の数
        return len(self.fuuro)

    def draw(self, cards: List[str], is_rinshan=False):
        self.hand.extend(cards)
        self.is_rinshan = is_rinshan  # set rinshan state for rinshan tsumo

    def discard(self, idx, is_riichi: bool) -> str:
        if idx > 13 - self.num_kan * 3:
            raise IndexError(idx)

        card = self.hand.pop(idx)
        self.kawa.append((card, is_riichi))

        if is_riichi:
            self.is_ippatsu = True
        else:
            self.is_ippatsu = False

        self.is_temp_furiten = False  # clear same-turn furiten on each discard

        return card

    def kan(self, kan_card: str) -> bool:
        if self.hand.count(kan_card) != 4 or len(self.hand) < 5:
            return False
        self.hand = [card for card in self.hand if card != kan_card]
        self.fuuro.append((kan_card, kan_card, kan_card, kan_card))
        self.num_kan += 1
        return True

    def get_info(self):
        info = {
            "is_oya": self.is_oya,
            "hand" : self.hand,
        }
        return info

class TurnState:
    BEFORE_DRAW = 1
    AFTER_DRAW = 2
    AFTER_DISCARD = 3
    def __init__(self, player_ids: List[str]) -> None:
        assert len(player_ids) == 2
        self.player_ids = player_ids
        self.current_player: str = None
        self.turn = 1
        self.stage: str = self.BEFORE_DRAW

    def __str__(self):
        return f"{self.turn}: {self.current_player} - {self.stage}"

    def next(self):
        if self.stage == self.BEFORE_DRAW:
            self.stage = self.AFTER_DRAW
        elif self.stage == self.AFTER_DRAW:
            self.stage = self.AFTER_DISCARD
        elif self.stage == self.AFTER_DISCARD:
            self.stage = self.BEFORE_DRAW
            self.current_player = self.player_ids[1 - self.player_ids.index(self.current_player)]
            self.turn += 1

    @property
    def is_before_draw(self):
        return self.stage == self.BEFORE_DRAW
    @property
    def is_after_draw(self):
        return self.stage == self.AFTER_DRAW
    @property
    def is_after_discard(self):
        return self.stage == self.AFTER_DISCARD


class ChinitsuGame:
    def __init__(self, rules: Dict=None, debug_code: int=None) -> None:
        self._players: Dict[str, ChinitsuPlayer] = {}
        self.status = WAITING
        self.yama : List[str] = []

        self.kyoutaku_number = 0
        self.tsumi_number = 0
        self.next_oya = None   # set after each round; None = randomize
        self._ready = set()    # tracks which players clicked start_new
        self.debug_code = debug_code if debug_code in debug_cards else None
        self.set_rules(rules)

    def set_rules(self, rules: dict):
        # Copy default_rules to avoid mutating the module-level dict across games.
        self.rules = dict(default_rules)
        if rules is not None:
            self.rules.update(rules)
        # Unpack yaku_rules dict as kwargs so has_daisharin/renhou_as_yakuman are passed correctly.
        self.agari_judger = AgariJudger(**self.rules['yaku_rules'])

    @property
    def player_ids(self):
        return list(self._players.keys())


    @property
    def is_waiting(self):
        return self.status == WAITING
    @property
    def is_running(self):
        return self.status == RUNNING
    @property
    def is_reconnecting(self):
        return self.status == RECONNECT
    @property
    def is_ended(self):
        return self.status == ENDED

    def set_waiting(self):
        self.status = WAITING
    def set_running(self):
        self.status = RUNNING
    def set_reconnecting(self):
        self.status = RECONNECT
    def set_ended(self):
        self.status = ENDED

    def draw_from_yama(self, player_name, cnt=1) -> List[str]:
        if cnt > len(self.yama):
            raise ValueError(f"Too few cards to draw! {cnt} > {len(self.yama)}")
        cards = self.yama[:cnt]
        self._players[player_name].draw(cards)
        self.yama = self.yama[cnt:]
        return cards

    def draw_from_rinshan(self, player_name) -> List[str]:
        if len(self.yama) <= 0:
            raise ValueError(f"Too few cards to draw! {len(self.yama)}")

        cards = [self.yama[-1]]
        self._players[player_name].draw(cards, is_rinshan=True)
        self.yama = self.yama[:-1]
        return cards

    def player(self, player_name) -> ChinitsuPlayer:
        return self._players[player_name]
    def other_player(self, player_name) -> ChinitsuPlayer:
        return self._players[self.player_ids[1 - self.player_ids.index(player_name)]]

    def start_new_game(self, debug_code=None):
        # use saved next_oya if available, otherwise randomize
        if self.next_oya and self.next_oya in self.player_ids:
            oya = self.next_oya
        else:
            idx = random.randint(0, 1)
            oya = self.player_ids[idx]
        # explicit arg takes priority; fall back to room-level debug_code
        self.start_game(oya, debug_code or self.debug_code)

    def start_game(self, oya: str, debug_code=None):

        if len(self._players) != 2:
            raise ValueError(f"Too few or too many players! {self.player_ids}")
        self.state = TurnState(self.player_ids)
        self.state.current_player = oya

        # randomize the yama and draw cards
        random.seed(time.time())
        if debug_code and debug_code in debug_cards:
            self.yama = debug_yama(debug_code)
        else:
            self.yama = ([f"{i}s" for i in range(1, 9+1)] * 4)[:]
            random.shuffle(self.yama)


        for _, p in self._players.items():
            p.reset_game()

        ko  = self.player_ids[1 - self.player_ids.index(oya)]
        self._players[oya].is_oya = True
        self._players[ko].is_oya = False

        # simulate drawing cards just for fun :)
        for _ in range(3):
            self.draw_from_yama(oya, 4)
            self.draw_from_yama(ko, 4)
        self.draw_from_yama(oya, 2)
        self.draw_from_yama(ko, 1)
        self.set_running()
        if self.rules.get('sort_hand'):
            # Oya has 14 tiles: sort first 13, keep tile 14 at end as tsumo tile.
            # Ko has 13 tiles: full sort is safe (ko draws before tsumo).
            oya_hand = self._players[oya].hand
            oya_hand[:-1] = sorted(oya_hand[:-1])
            self._players[ko].hand.sort()



    def _sort_hand_if_enabled(self, player_name: str):
        if self.rules.get('sort_hand'):
            hand = self._players[player_name].hand
            if len(hand) > 1:
                # Sort all tiles except the last (newly drawn) tile so that
                # hand[-1] always points to the tsumo tile for win evaluation.
                hand[:-1] = sorted(hand[:-1])

    def add_player(self, player_name: str):
        if len(self._players) >= 2:
            raise AssertionError(f"Too many Players ({len(self._players)})!")
        if player_name in self._players:
            raise ValueError(f"{player_name} exists!")
        self._players[player_name] = ChinitsuPlayer(player_name, initial_point=self.rules['initial_point'])

    def activate_player(self, player_name):
        if player_name not in self._players:
            raise ValueError(player_name)
        self._players[player_name].active = True

    def deactivate_player(self, player_name):
        if player_name not in self._players:
            raise ValueError(player_name)
        self._players[player_name].active = False

    @classmethod
    def from_snapshot(cls, snapshot: dict, rules: dict = None) -> "ChinitsuGame":
        """
        从快照字典重建 ChinitsuGame 对象，用于服务重启后恢复游戏状态。
        快照必须包含 'yama' 字段（serialize_game 生成的新格式快照）。
        """
        game = cls(rules=rules)

        players_data = snapshot.get("players", {})
        player_ids = list(players_data.keys())

        for pid in player_ids:
            game.add_player(pid)
            p = game._players[pid]
            pdata = players_data[pid]

            p.point             = pdata.get("point", 0)
            p.is_oya            = pdata.get("is_oya", False)
            p.is_riichi         = pdata.get("is_riichi", False)
            p.is_daburu_riichi  = pdata.get("is_daburu_riichi", False)
            p.riichi_turn       = pdata.get("riichi_turn")
            p.is_ippatsu        = pdata.get("is_ippatsu", False)
            p.is_rinshan        = pdata.get("is_rinshan", False)
            p.is_furiten        = pdata.get("is_furiten", False)
            p.is_temp_furiten   = pdata.get("is_temp_furiten", False)
            p.hand   = list(pdata.get("hand", []))
            p.fuuro  = [tuple(f) for f in pdata.get("fuuro", [])]
            p.kawa   = [(k[0], k[1]) for k in pdata.get("kawa", [])]
            p.num_kan = pdata.get("num_kan", 0)

        game.yama             = list(snapshot["yama"])   # KeyError if absent → caller handles
        game.kyoutaku_number  = snapshot.get("kyoutaku_number", 0)
        game.tsumi_number     = snapshot.get("tsumi_number", 0)
        game.next_oya         = snapshot.get("next_oya")

        stage_map = {
            "before_draw":  TurnState.BEFORE_DRAW,
            "after_draw":   TurnState.AFTER_DRAW,
            "after_discard": TurnState.AFTER_DISCARD,
        }
        game.state = TurnState(player_ids)
        game.state.current_player = snapshot.get("current_player_id", player_ids[0] if player_ids else "")
        game.state.turn  = snapshot.get("turn_number", 1)
        game.state.stage = stage_map.get(snapshot.get("turn_stage", "before_draw"), TurnState.BEFORE_DRAW)

        game.status = RUNNING
        return game

    def remove_player(self, player_name: str):
        if self.is_running or self.is_reconnecting:
            raise AssertionError("Cannot remove player in game!")
        if player_name not in self._players:
            raise ValueError(player_name)
        self._players.pop(player_name)


    def input(self, action: str, card_idx: int, player_id: str) -> bool:

        # public info to be retured to every connection
        public_info = {
            "player_id": player_id,
            "action" : action,
            "card_idx" : None,         # index of card played or drawn, depending on action
            "card" : None,
            "fuuro" : {
                name: p.fuuro for name, p in self._players.items()
            },
            "kawa" : {
                name: p.kawa for name, p in self._players.items()
            },
        }

         # start the game
        if action in ["start_new", "start"]:
            debug_code = card_idx if card_idx and card_idx > 100 else None
            if debug_code:
                logger.warning('Debug code: %s', debug_code)

            if len(self._players) != 2:
                return {player_id: {"message": "not_enough_players"}}

            # both players must signal ready before the round starts
            self._ready.add(player_id)
            if len(self._ready) < 2:
                return {player_id: {"action": action, "message": "waiting_for_opponent"}}
            self._ready.clear()

            self.start_new_game(debug_code=debug_code)
            self.state.next()  # oya does not need to draw, set to after_draw
            # Refresh fuuro/kawa after reset_game() has been called
            public_info["fuuro"] = {name: p.fuuro for name, p in self._players.items()}
            public_info["kawa"] = {name: p.kawa for name, p in self._players.items()}
            res = {player_id: {"message": "ok"}}
            for name, p in self._players.items():
                if name not in res:
                    res[name] = {}
                res[name]["hand"] = p.hand
                res[name]["is_oya"] = p.is_oya



        p   = self.player(player_id)
        opp = self.other_player(player_id)
        is_tenchii_tenpai = (self.state.turn in [1, 2] and all([p.num_kan == 0 for _, p in self._players.items()]))
        # res = None



        # check if action turn is legal
        if action in ["discard", "draw", "tsumo", "riichi", "kan"] and self.state.current_player != player_id:
            res = {player_id: {"message": "not_your_turn"}}
            return res
        if action in ["ron", "skip_ron"] and self.state.current_player == player_id:
            res = {player_id: {"message": "not_opponent_turn"}}
            return res
        if action in ["discard", "riichi", "kan"] and (card_idx is None or not (0 <= card_idx < 14 - self._players[player_id].num_kan)):
            res = {player_id: {"message": "card_index_error"}}
            return res


        if action == "draw":
            if p.is_oya and self.state.turn == 1 or not self.state.is_before_draw:  # oya does not draw in first turn; can't draw twice
                res = {player_id: {"message": "illegal_draw"}}
                logger.debug(str(self.state))
                return res
            if len(self.yama) == 0:
                # Exhaustive draw — ryukyoku
                tenpai_info = {}
                for name, pl in self._players.items():
                    tiles = get_tenpai_tiles(pl.hand, pl.num_fuuro)
                    tenpai_info[name] = {"is_tenpai": bool(tiles), "hand": pl.hand if tiles else []}

                # Illegal riichi kan penalty (deferred chombo)
                # Rule: violator who is tenpai at ryukyoku pays -20,000.
                # Double chombo: if both violate, penalties cancel out (no change).
                chombo_players = [
                    name for name, pl in self._players.items()
                    if pl.has_illegal_kan and tenpai_info[name]["is_tenpai"]
                ]
                if len(chombo_players) == 2:
                    # Double chombo — cancel out, no score change
                    logger.info("Double chombo at ryukyoku — penalties cancelled")
                    public_info["double_chombo"] = True
                elif len(chombo_players) == 1:
                    offender = chombo_players[0]
                    other = [n for n in self.player_ids if n != offender][0]
                    punishment = self.rules['no_agari_punishment']
                    self._players[offender].point -= punishment
                    self._players[other].point += punishment
                    logger.info("Chombo at ryukyoku: %s pays %d", offender, punishment)
                    public_info["chombo"] = offender

                public_info["ryukyoku"] = True
                public_info["tenpai"] = tenpai_info
                self.set_ended()
                res = {player_id: {"message": "ok"}}
            else:
                cards = self.draw_from_yama(player_id)
                self._sort_hand_if_enabled(player_id)
                public_info["card_idx"] = p.len_hand
                res = {player_id: {"hand": p.hand}}
                self.state.next()


        if action == "kan":
            if not self.state.is_after_draw:
                res = {player_id: {"message": "illegal_kan"}}
                return res
            kan_card = p.hand[card_idx] # kan card type

            # Riichi kan legality check: silently flag but allow the kan to proceed.
            # Penalty is deferred until the violator attempts to win or reach ryukyoku tenpai.
            if p.is_riichi and not _is_riichi_kan_legal(p, kan_card):
                logger.info("Illegal riichi kan by %s (card: %s) — deferred penalty set", player_id, kan_card)
                p.has_illegal_kan = True

            if not p.kan(kan_card):
                res = {player_id: {"message": f"too_few_cards_to_kan. ({kan_card})"}}
                return res
            public_info["card_idx"] = card_idx
            public_info["card"] = kan_card

            rinshan_card = self.draw_from_rinshan(player_id)
            self._sort_hand_if_enabled(player_id)
            # cancel ippatsu of all players after kan
            for _, pl in self._players.items():
                pl.is_ippatsu = False

            res = {player_id: {"message": "ok", "hand": p.hand}}


        if action == "discard":
            if not self.state.is_after_draw:
                res = {player_id: {"message": "illegal_discard"}}

                return res
            try:
                card = p.discard(card_idx, is_riichi=False)
                if self.rules.get('sort_hand'):
                    p.hand.sort()
                public_info["card_idx"] = card_idx
                public_info["card"] = card
                res = {player_id: {"message": "ok", "hand": p.hand}}
                self.state.next()
            except IndexError as e:
                res = {player_id: {"message": f"card_index_out_of_range. {e}"}}
                return res

        if action == "riichi":
            if not self.state.is_after_draw:
                res = {player_id: {"message": "illegal_riichi"}}
                return res
            if p.is_riichi:
                res = {player_id: {"message": f"cannot_riichi_twice"}}
                return res
            try:
                card = p.discard(card_idx, is_riichi=True)
                if self.rules.get('sort_hand'):
                    p.hand.sort()
                p.is_riichi = True
                p.riichi_machi = set(get_tenpai_tiles(p.hand))  # save machi for later kan checks
                if is_tenchii_tenpai:
                    p.is_daburu_riichi = True
                p.riichi_turn = self.state.turn

                public_info["card_idx"] = card_idx
                public_info["card"] = card
                res = {player_id: {"message": "ok", "hand": p.hand}}
                self.state.next()
            except IndexError as e:
                res = {player_id: {"message": f"card_index_out_of_range. {e}"}}
                return res


        def process_agari(agari: HandResponse, is_tsumo: bool, is_oya: bool):
            is_agari = (agari.han is not None and agari.han > 0)
            res = {player_id: {"message": "ok"}}
            if is_agari:
                if is_tsumo:
                    if is_oya:
                        # Dealer tsumo: 3 non-dealers each pay main (+bonus for honba)
                        per_player = agari.cost['main'] + agari.cost.get('main_bonus', 0)
                        win_amount = 3 * per_player
                    else:
                        # Non-dealer tsumo: dealer pays main, 2 non-dealers each pay additional
                        main = agari.cost['main'] + agari.cost.get('main_bonus', 0)
                        additional = agari.cost['additional'] + agari.cost.get('additional_bonus', 0)
                        win_amount = main + 2 * additional
                else:
                    # Ron: loser pays the full amount directly
                    win_amount = agari.cost['main'] + agari.cost.get('main_bonus', 0)
                # winner gains points (including kyoutaku sticks), loser pays base cost
                p.point += win_amount + self.kyoutaku_number * 1000
                opp.point -= win_amount
                self.kyoutaku_number = 0
                # winner is next oya
                self.next_oya = player_id
                p.is_oya = True
                opp.is_oya = False
                winner_hand = list(p.hand) if is_tsumo else list(p.hand) + [opp.kawa[-1][0]]
                public_info.update({
                    "agari": True,
                    "han": agari.han,
                    "fu": agari.fu,
                    "point": win_amount,
                    "yaku": [str(y) for y in agari.yaku],
                    "winner_hand": winner_hand,
                })
            else:
                punishment = self.rules['no_agari_punishment']
                # false winner pays, opponent receives
                p.point -= punishment
                opp.point += punishment
                # opponent becomes next oya
                self.next_oya = opp.name
                opp.is_oya = True
                p.is_oya = False
                public_info.update({
                    "agari": False,
                    "han": 0,
                    "fu": 0,
                    "point": -punishment,
                    "yaku": None,
                    "error": agari.error
                })
            self.set_ended()
            return res

        if action == "tsumo":
            if not self.state.is_after_draw:
                res = {player_id: {"message": "illegal_tsumo"}}
                return res
            if p.len_hand + p.num_fuuro * 3 != 14:
                res = {player_id: {"message": f"incorrect_card_count: {p.len_hand} + {p.num_fuuro} fuuros"}}
                return res

            # Deferred chombo: illegal riichi kan detected earlier — treat as false agari
            if p.has_illegal_kan:
                logger.info("Chombo: illegal riichi kan by %s — applying penalty on tsumo", player_id)
                res = process_agari(HandResponse(error="illegal_kan_chombo"), is_tsumo=True, is_oya=p.is_oya)
                return res

            agari_condition = {
                "is_tsumo" : True,
                "is_riichi": p.is_riichi,
                "is_ippatsu": p.is_ippatsu,
                "is_rinshan": p.is_rinshan,
                "is_haitei": (len(self.yama) == 0),
                "is_houtei": False,
                "is_daburu_riichi": (p.is_riichi and p.is_daburu_riichi),
                "is_tenhou": (p.is_oya and is_tenchii_tenpai),
                "is_renhou": False,
                "is_chiihou": ((not p.is_oya) and is_tenchii_tenpai),
                "is_open_riichi": False,
                "is_oya": p.is_oya,
                "kyoutaku_number": self.kyoutaku_number,
                "tsumi_number": self.tsumi_number,

            }

            agari = self.agari_judger.judge(p.hand, p.fuuro, p.hand[-1], **agari_condition)
            res = process_agari(agari, is_tsumo=True, is_oya=p.is_oya)


        if action == 'ron':
            if not self.state.is_after_discard:
                res = {player_id: {"message": "illegal_ron"}}
                return res
            if p.len_hand + p.num_fuuro * 3 != 13:
                res = {player_id: {"message": f"incorrect_card_count: {p.len_hand} + {p.num_fuuro} fuuros"}}
                return res

            # Deferred chombo: illegal riichi kan — treat as false agari
            if p.has_illegal_kan:
                logger.info("Chombo: illegal riichi kan by %s — applying penalty on ron", player_id)
                res = process_agari(HandResponse(error="illegal_kan_chombo"), is_tsumo=False, is_oya=p.is_oya)
                return res

            # Furiten checks — all three types block ron (tsumo is still allowed)
            if p.is_furiten or p.is_temp_furiten:
                res = process_agari(HandResponse(error="furiten"), is_tsumo=False, is_oya=p.is_oya)
                return res
            tenpai_tiles = get_tenpai_tiles(p.hand, p.num_fuuro)
            kawa_cards = {k[0] for k in p.kawa}
            if any(t in kawa_cards for t in tenpai_tiles):
                res = process_agari(HandResponse(error="furiten"), is_tsumo=False, is_oya=p.is_oya)
                return res

            agari_condition = {
                "is_tsumo" : False,
                "is_riichi": p.is_riichi,
                "is_ippatsu": p.is_ippatsu,
                "is_rinshan": False,
                "is_haitei": False,
                "is_houtei": (len(self.yama) == 0),
                "is_daburu_riichi": (p.is_riichi and p.is_daburu_riichi),
                "is_tenhou": False,
                "is_renhou": is_tenchii_tenpai,
                "is_chiihou": False,
                "is_open_riichi": False,
                "is_oya": p.is_oya,
                "kyoutaku_number": self.kyoutaku_number,
                "tsumi_number": self.tsumi_number,

            }

            ron_tile = opp.kawa[-1][0]
            logger.debug("RON attempt: %s hand=%s fuuro=%s win=%s riichi=%s",
                         player_id, p.hand, p.fuuro, ron_tile, p.is_riichi)
            agari = self.agari_judger.judge(p.hand + [ron_tile], p.fuuro, ron_tile, **agari_condition)
            logger.debug("RON result: han=%s error=%s", agari.han, agari.error)
            res = process_agari(agari, is_tsumo=False, is_oya=p.is_oya)

        # skip opponent turn (choose not to ron)
        if action == "skip_ron":
            if not self.state.is_after_discard:
                res = {player_id: {"message": "illegal_skip_ron"}}
                return res

            # opponent should give 1000 point kyoutaku if opponent just riichi'ed
            if opp.kawa[-1][1]:
                opp.point -= 1000
                self.kyoutaku_number += 1

            # Set furiten if player skipped a tile they could have won on
            win_card = opp.kawa[-1][0]
            tenpai_tiles = get_tenpai_tiles(p.hand, p.num_fuuro)
            if win_card in tenpai_tiles:
                if p.is_riichi:
                    p.is_furiten = True       # permanent: riichi furiten
                else:
                    p.is_temp_furiten = True  # temporary: same-turn furiten
            res = {player_id: {"message": "ok"}}
            self.state.next()

        # add current point balances and public info to result
        public_info["balances"] = {name: pl.point for name, pl in self._players.items()}
        for p_id in self.player_ids:
            if p_id not in res:
                res[p_id] = {}
            res[p_id].update(public_info)

        return res