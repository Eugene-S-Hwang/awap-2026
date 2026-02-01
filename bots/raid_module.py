

from typing import Tuple, Optional
from collections import deque
from enum import Enum


class RaidState(Enum):
    IDLE = 0
    SWITCHING_TO_ENEMY = 1
    FINDING_MEAT = 2
    MOVING_TO_MEAT = 3
    PICKING_UP_MEAT = 4
    FINDING_TRASH = 5
    MOVING_TO_TRASH = 6
    TRASHING_MEAT = 7
    COMPLETE = 8
    FAILED = 9


class RaidController:
    
    def __init__(self, raid_timeout_turn=350):
        self.state = RaidState.IDLE
        self.meat_location = None
        self.trash_location = None
        self.raid_complete = False
        self.raid_timeout_turn = raid_timeout_turn  # Turn by which raid must end
        self.raid_start_turn = None  # Track when raid started
        
    def reset(self):
        self.state = RaidState.IDLE
        self.meat_location = None
        self.trash_location = None
        self.raid_complete = False
        self.raid_start_turn = None
    
    def is_complete(self) -> bool:
        return self.state in [RaidState.COMPLETE, RaidState.FAILED]
    
    def get_bfs_path(self, controller, start: Tuple[int, int], target_predicate) -> Optional[Tuple[int, int]]:
        queue = deque([(start, [])])
        visited = set([start])
        m = controller.get_map()
        w, h = m.width, m.height

        while queue:
            (curr_x, curr_y), path = queue.popleft()
            tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
            
            if target_predicate(curr_x, curr_y, tile):
                if not path:
                    return (0, 0)
                return path[0]

            for dx in [0, -1, 1]:
                for dy in [0, -1, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = curr_x + dx, curr_y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if m.is_tile_walkable(nx, ny):
                            visited.add((nx, ny))
                            queue.append(((nx, ny), path + [(dx, dy)]))
        return None
    
    def move_towards(self, controller, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        
        # Check if already adjacent
        if max(abs(bx - target_x), abs(by - target_y)) <= 1:
            return True
        
        # Find next step
        def is_adjacent(x, y, tile):
            return max(abs(x - target_x), abs(y - target_y)) <= 1
        
        step = self.get_bfs_path(controller, (bx, by), is_adjacent)
        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
        
        return False
    
    def find_nearest_meat(self, controller, bot_x: int, bot_y: int) -> Optional[Tuple[int, int]]:
        best_dist = 9999
        best_pos = None
        m = controller.get_map()
        
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                
                # Check if tile can hold items
                if tile.tile_name in ["COUNTER", "BOX"] and tile.item is not None:
                    item_dict = controller.item_to_public_dict(tile.item)
                    
                    # Check if it's meat
                    if item_dict and item_dict.get('type') == 'Food':
                        if item_dict.get('food_name') == 'MEAT':
                            dist = max(abs(bot_x - x), abs(bot_y - y))
                            if dist < best_dist:
                                best_dist = dist
                                best_pos = (x, y)
        
        return best_pos
    
    def find_nearest_trash(self, controller, bot_x: int, bot_y: int) -> Optional[Tuple[int, int]]:
        best_dist = 9999
        best_pos = None
        m = controller.get_map()
        
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == "TRASH":
                    dist = max(abs(bot_x - x), abs(bot_y - y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        
        return best_pos
    
    def execute_raid(self, controller, bot_id: int) -> bool:
        if self.is_complete():
            return False
        
        current_turn = controller.get_turn()
        
        # Track when raid started
        if self.raid_start_turn is None and self.state != RaidState.IDLE:
            self.raid_start_turn = current_turn
        
        # Check timeout - must switch back by timeout turn
        if current_turn >= self.raid_timeout_turn:
            bot_info = controller.get_bot_state(bot_id)
            if bot_info:
                current_team = bot_info.get('map_team')
                my_team = controller.get_team()
                
                # If still on enemy map, need to switch back
                if current_team != my_team:
                    print(f"[RAID] Timeout at turn {current_turn}, switching back to home map")
                    if controller.can_switch_maps():
                        if controller.switch_maps():
                            print(f"[RAID] Successfully returned to home map")
                            self.state = RaidState.COMPLETE
                            self.raid_complete = True
                            return False
                    # If can't switch, we're stuck - mark as complete anyway
                    print(f"[RAID] Cannot switch back (already used switch)")
                    self.state = RaidState.COMPLETE
                    self.raid_complete = True
                    return False
                else:
                    # Already on home map
                    print(f"[RAID] Timeout - already on home map")
                    self.state = RaidState.COMPLETE
                    self.raid_complete = True
                    return False
        
        bot_info = controller.get_bot_state(bot_id)
        if not bot_info:
            self.state = RaidState.FAILED
            return False
        
        bx, by = bot_info['x'], bot_info['y']
        current_team = bot_info.get('map_team')
        my_team = controller.get_team()
        enemy_team = controller.get_enemy_team()
        
        # State machine for raid sequence
        
        if self.state == RaidState.IDLE:
            # Start the raid
            self.state = RaidState.SWITCHING_TO_ENEMY
        
        elif self.state == RaidState.SWITCHING_TO_ENEMY:
            # Check if already on enemy map
            if current_team == enemy_team:
                self.state = RaidState.FINDING_MEAT
                return True
            
            # Try to switch
            if controller.can_switch_maps():
                if controller.switch_maps():
                    print(f"[RAID] Bot {bot_id} switched to enemy map")
                    self.state = RaidState.FINDING_MEAT
                else:
                    print(f"[RAID] Failed to switch maps")
                    self.state = RaidState.FAILED
            else:
                print(f"[RAID] Cannot switch yet (turn {controller.get_turn()})")
                # Wait until we can switch
                if controller.get_turn() < 250:
                    return True
                else:
                    self.state = RaidState.FAILED
        
        elif self.state == RaidState.FINDING_MEAT:
            # Verify we're on enemy map
            if current_team != enemy_team:
                self.state = RaidState.SWITCHING_TO_ENEMY
                return True
            
            # Find meat
            meat_loc = self.find_nearest_meat(controller, bx, by)
            if meat_loc:
                self.meat_location = meat_loc
                print(f"[RAID] Found meat at {meat_loc}")
                self.state = RaidState.MOVING_TO_MEAT
            else:
                print(f"[RAID] No meat found on enemy map")
                self.state = RaidState.FAILED
        
        elif self.state == RaidState.MOVING_TO_MEAT:
            if not self.meat_location:
                self.state = RaidState.FINDING_MEAT
                return True
            
            mx, my = self.meat_location
            if self.move_towards(controller, bot_id, mx, my):
                self.state = RaidState.PICKING_UP_MEAT
        
        elif self.state == RaidState.PICKING_UP_MEAT:
            if not self.meat_location:
                self.state = RaidState.FINDING_MEAT
                return True
            
            mx, my = self.meat_location
            if controller.pickup(bot_id, mx, my):
                print(f"[RAID] Picked up meat from enemy!")
                self.state = RaidState.FINDING_TRASH
            else:
                # Pickup failed, meat might be gone
                print(f"[RAID] Failed to pickup meat, searching again")
                self.meat_location = None
                self.state = RaidState.FINDING_MEAT
        
        elif self.state == RaidState.FINDING_TRASH:
            trash_loc = self.find_nearest_trash(controller, bx, by)
            if trash_loc:
                self.trash_location = trash_loc
                print(f"[RAID] Found trash at {trash_loc}")
                self.state = RaidState.MOVING_TO_TRASH
            else:
                print(f"[RAID] No trash found on enemy map")
                self.state = RaidState.FAILED
        
        elif self.state == RaidState.MOVING_TO_TRASH:
            if not self.trash_location:
                self.state = RaidState.FINDING_TRASH
                return True
            
            tx, ty = self.trash_location
            if self.move_towards(controller, bot_id, tx, ty):
                self.state = RaidState.TRASHING_MEAT
        
        elif self.state == RaidState.TRASHING_MEAT:
            if not self.trash_location:
                self.state = RaidState.FINDING_TRASH
                return True
            
            tx, ty = self.trash_location
            if controller.trash(bot_id, tx, ty):
                print(f"[RAID] Successfully trashed enemy meat! Raid complete!")
                self.raid_complete = True
                self.state = RaidState.COMPLETE
            else:
                print(f"[RAID] Failed to trash meat")
                self.state = RaidState.FAILED
        
        return not self.is_complete()


def simple_raid(controller, bot_id: int, raid_timeout_turn: int = 350) -> bool:
    # Create singleton instance
    if not hasattr(simple_raid, 'controller'):
        simple_raid.controller = RaidController(raid_timeout_turn=raid_timeout_turn)
    
    return simple_raid.controller.execute_raid(controller, bot_id)