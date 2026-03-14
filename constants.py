import numpy as np

# Define standard CubiCasa5k classes
ROOM_CLASSES = [
    "Background", "Outdoor", "Wall", "Kitchen", "Living Room", 
    "Bed Room", "Bath", "Entry", "Railing", "Storage", "Garage", "Undefined"
]

ICON_CLASSES = [
    "No Icon", "Window", "Door", "Closet", "Electrical Appliance", 
    "Toilet", "Sink", "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
]

def get_class_colors():
    """
    Generates the same color maps used in inference.
    Returns (room_colors, icon_colors).
    """
    np.random.seed(42)
    
    # Room colors (13 to be safe, for 12 classes)
    room_colors = np.random.randint(100, 255, (13, 3), dtype=np.uint8)
    room_colors[0] = [0, 0, 0]
    
    # Icon colors
    icon_colors = np.random.randint(0, 200, (12, 3), dtype=np.uint8)
    icon_colors[0] = [0, 0, 0]
    
    return room_colors, icon_colors