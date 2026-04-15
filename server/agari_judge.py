from typing import List, Dict, Tuple
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.meld import Meld
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.shanten import Shanten
from mahjong.tile import TilesConverter
from mahjong.hand_calculating.hand_response import HandResponse
from mahjong.constants import EAST, SOUTH, WEST, NORTH

# useful helper
def print_hand_result(hand_result):
    print(hand_result.han, hand_result.fu)
    print(hand_result.cost['main'])
    print(hand_result.yaku)
    for fu_item in hand_result.fu_details:
        print(fu_item)
    print('')


calculator = HandCalculator()
_shanten = Shanten()

def get_tenpai_tiles(hand: List[str], num_fuuro: int = 0) -> List[str]:
    """Given a 13-tile hand, return the list of tiles that would complete it."""
    winning = []
    for num in range(1, 10):
        test = hand + [f"{num}s"]
        hand_str = ''.join(sorted([s.strip('s') for s in test]))
        tiles = TilesConverter.string_to_34_array(sou=hand_str)
        if _shanten.calculate_shanten(tiles) == -1:
            winning.append(f"{num}s")
    return winning


class AgariJudger():    
    def __init__(self, has_daisharin=False, renhou_as_yakuman=False, ) -> None:
        self.calculator = HandCalculator()
        self.options = OptionalRules(has_open_tanyao=False,
                                     has_aka_dora=False,
                                     has_double_yakuman=True,
                                     has_daisharin=has_daisharin,
                                     has_daisharin_other_suits=has_daisharin,
                                     renhou_as_yakuman=renhou_as_yakuman,
                                     )
    
    
    def judge(self, hand: List[str],
              fuuro: List[Tuple[str]],
              win_card: str,
              is_tsumo=False,
              is_riichi=False,
              is_ippatsu=False,
              is_rinshan=False,
              is_haitei=False,
              is_houtei=False,
              is_daburu_riichi=False,
              is_tenhou=False,
              is_renhou=False,
              is_chiihou=False,
              is_open_riichi=False,
              is_oya=False,
              kyoutaku_number=0,
              tsumi_number=0) -> HandResponse:
        # Include fuuro tiles in the full tile set (required for correct hand evaluation)
        all_cards = list(hand)
        for meld in fuuro:
            all_cards.extend(meld)
        hand_souzi_str = ''.join(sorted([s.strip('s') for s in all_cards]))
        tiles = TilesConverter.string_to_136_array(sou=hand_souzi_str)
        win_tile = TilesConverter.string_to_136_array(sou=win_card.strip('s'))[0]

        # Build closed Meld objects for each kan in fuuro
        melds = []
        for meld in fuuro:
            meld_str = ''.join(sorted([s.strip('s') for s in meld]))
            meld_tiles = TilesConverter.string_to_136_array(sou=meld_str)
            melds.append(Meld(meld_type=Meld.KAN, tiles=meld_tiles, opened=False))

        result: HandResponse = calculator.estimate_hand_value(tiles,
                                                              win_tile,
                                                              melds=melds if melds else None,
                                                              config=HandConfig(options=self.options,
                                                                                is_tsumo=is_tsumo,
                                                                                is_riichi=is_riichi,
                                                                                is_ippatsu=is_ippatsu,
                                                                                is_rinshan=is_rinshan,
                                                                                is_haitei=is_haitei,
                                                                                is_houtei=is_houtei,
                                                                                is_daburu_riichi=is_daburu_riichi,
                                                                                is_tenhou=is_tenhou,
                                                                                is_renhou=is_renhou,
                                                                                is_chiihou=is_chiihou,
                                                                                is_open_riichi=is_open_riichi,
                                                                                player_wind=(EAST if is_oya else NORTH),
                                                                                kyoutaku_number=kyoutaku_number,
                                                                                tsumi_number=tsumi_number)
                                                            )
        return result
        