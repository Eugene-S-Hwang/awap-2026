import random
from collections import deque
from typing import Tuple, Optional, List

from game_constants import Team, TileType, FoodType, ShopCosts
from robot_controller import RobotController
from item import Pan, Plate, Food
from enum import Enum

class States(Enum):
    NOTHING = -1
    INIT = 0
    BUY_PAN = 1
    BUY_FOOD = 2
    PLACE_ON_COUNTER = 3
    CHOP_FOOD = 4
    PICKUP_CHOPPED = 5
    COOK_FOOD = 6
    BUY_PLATE = 7
    PLACE_PLATE = 8
    ADD_FOOD = 9
    WAIT_AND_TAKE = 10
    SUBMIT = 11
    WASH_DISH = 12
    GET_PLATE_FROM_SINKTABLE = 13
    TRASH = 14


class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        self.assembly_counter = None 
        self.cooker_loc = None
        self.submit_pos = None
        self.sink_pos = None
        self.sinktable_pos = None
        self.my_bot_id = None
        self.current_order = None
        
        self.state = States.INIT
        

    def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], target_predicate) -> Optional[Tuple[int, int]]:
        queue = deque([(start, [])]) 
        visited = set([start])
        w, h = self.map.width, self.map.height

        while queue:
            (curr_x, curr_y), path = queue.popleft()
            tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
            if target_predicate(curr_x, curr_y, tile):
                if not path: return (0, 0) 
                return path[0] 

            for dx in [0, -1, 1]:
                for dy in [0, -1, 1]:
                    if dx == 0 and dy == 0: continue
                    nx, ny = curr_x + dx, curr_y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if controller.get_map().is_tile_walkable(nx, ny):
                            visited.add((nx, ny))
                            queue.append(((nx, ny), path + [(dx, dy)]))
        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        def is_adjacent_to_target(x, y, tile):
            return max(abs(x - target_x), abs(y - target_y)) <= 1
        if is_adjacent_to_target(bx, by, None): return True
        step = self.get_bfs_path(controller, (bx, by), is_adjacent_to_target)
        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
            return False 
        return False 

    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
        best_dist = 9999
        best_pos = None
        m = controller.get_map()
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == tile_name:
                    dist = max(abs(bot_x - x), abs(bot_y - y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        return best_pos

    def play_turn(self, controller: RobotController):
        my_bots = controller.get_team_bot_ids()
        if not my_bots: return
    
        self.my_bot_id = my_bots[0]
        bot_id = self.my_bot_id

        self.orders = controller.get_orders()
        if(not self.current_order):
            for order in self.orders:
                # print("Check: ", order["claimed_by"])
                if order["claimed_by"] is None:
                    self.current_order = order
                    break
        
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']

        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        if self.submit_pos is None:
            self.submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
        if self.sink_pos is None:
            self.sink_pos = self.find_nearest_tile(controller, bx, by, "SINK")
        if self.sinktable_pos is None:
            self.sinktable_pos = self.find_nearest_tile(controller, bx, by, "SINKTABLE")

        if not self.assembly_counter or not self.cooker_loc or not self.submit_pos: 
            return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc
        ux, uy = self.submit_pos
        wx, wy = self.sink_pos
        stx, sty = self.sinktable_pos

        if self.state in [2, 8, 10] and bot_info.get('holding'):
            self.state = 16

        #state 0: init + checking the pan
            
        # print(self.state)
        if self.state == States.INIT:
            if(not self.current_order):
                self.state = States.NOTHING
            else:
                kTile = controller.get_tile(controller.get_team(), kx, ky)
                uTile = controller.get_tile(controller.get_team(), ux, uy)
                if kTile and isinstance(kTile.item, Pan) and uTile and isinstance(uTile.item, Plate):
                    self.state = States.BUY_FOOD
                elif kTile and isinstance(kTile.item, Pan):
                    self.state = States.BUY_PLATE
                else:
                    self.state = States.BUY_PAN

        #state 1: buy pan
        elif self.state == States.BUY_PAN:
            holding = bot_info.get('holding')
            if holding: # check if it is a pan if needed
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        self.state = States.INIT
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos: return
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money() >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        #state 2: buy meat
        elif self.state == States.BUY_FOOD:
            if len(self.current_order["required"]) == 0:
                self.state = States.SUBMIT
            else:
                buyFood = self.current_order["required"].pop()
                # print(buyFood)
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if(buyFood == "MEAT"):
                        if controller.get_team_money() >= FoodType.MEAT.buy_cost:
                            if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                                self.state = States.PLACE_ON_COUNTER
                    elif(buyFood == "EGG"):
                        if controller.get_team_money() >= FoodType.EGG.buy_cost:
                            if controller.buy(bot_id, FoodType.EGG, sx, sy):
                                self.state = States.COOK_FOOD
                    elif(buyFood == "ONIONS"):
                        if controller.get_team_money() >= FoodType.ONIONS.buy_cost:
                            if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                                self.state = States.PLACE_ON_COUNTER
                    elif(buyFood == "NOODLES"):
                        if controller.get_team_money() >= FoodType.NOODLES.buy_cost:
                            if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                                self.state = States.ADD_FOOD
                    elif(buyFood == "SAUCE"):
                        if controller.get_team_money() >= FoodType.SAUCE.buy_cost:
                            if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                                self.state = States.ADD_FOOD

        elif self.state == States.PLACE_ON_COUNTER:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = States.CHOP_FOOD

        elif self.state == States.CHOP_FOOD:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state = States.PICKUP_CHOPPED

        #state 5: pickup meat
        elif self.state == States.PICKUP_CHOPPED:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    food = controller.get_bot_state(bot_id)["holding"]
                    # print(food)
                    if(food["food_id"] in [0, 2]):
                        self.state = States.COOK_FOOD
                    else:
                        self.state = States.ADD_FOOD

        elif self.state == States.COOK_FOOD:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    self.state = States.WAIT_AND_TAKE

        #state 8: buy the plate
        elif self.state == States.BUY_PLATE:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money() >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = States.PLACE_PLATE

        elif self.state == States.PLACE_PLATE:
            if not bot_info["holding"]:
                controller.pickup(bot_id, bx, by)
            else:
                if self.move_towards(controller, bot_id, ux, uy):
                    if controller.place(bot_id, ux, uy):
                        self.state = States.INIT

        elif self.state == States.ADD_FOOD:
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.add_food_to_plate(bot_id, ux, uy):
                    self.state = States.INIT

        elif self.state == States.WAIT_AND_TAKE:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = States.ADD_FOOD
                    elif food.cooked_stage == 2:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = States.TRASH

        elif self.state == States.SUBMIT:
            if self.move_towards(controller, bot_id, ux, uy):
                if not bot_info["holding"]:
                    controller.pickup(bot_id, ux, uy)
                else:
                    if controller.submit(bot_id, ux, uy):
                        self.current_order = None
                        self.state = States.WASH_DISH
        
        elif self.state == States.WASH_DISH:
            if self.move_towards(controller, bot_id, wx, wy):
                if controller.wash_sink(bot_id, wx, wy):
                    self.state = States.GET_PLATE_FROM_SINKTABLE
        
        elif self.state == States.GET_PLATE_FROM_SINKTABLE:
            if self.move_towards(controller, bot_id, stx, sty):
                if controller.pickup(bot_id, stx, sty):
                    self.state = States.PLACE_PLATE

        elif self.state == 16:
            trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    if bot_info["holding"].type == "Food":
                        self.current_order["required"].append(bot_info["holding"].food_name)
                    self.state = States.BUY_FOOD #restart
        elif self.state == States.NOTHING:
            for i in range(1, len(my_bots)):
                self.my_bot_id = my_bots[i]
                bot_id = self.my_bot_id
                
                bot_info = controller.get_bot_state(bot_id)
                bx, by = bot_info['x'], bot_info['y']

                dx = random.choice([-1, 1])
                dy = random.choice([-1, 1])
                nx,ny = bx + dx, by + dy
                if controller.get_map().is_tile_walkable(nx, ny):
                    controller.move(bot_id, dx, dy)
                    return