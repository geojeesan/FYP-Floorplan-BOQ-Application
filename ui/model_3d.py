import os
import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph
import pyqtgraph.opengl as gl
from shapely.geometry import Polygon, LineString
from shapely.ops import triangulate

class ThreeDViewer(QWidget):
    def __init__(self, boq_data, wall_height, scale_ratio=None):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.view = gl.GLViewWidget()
        self.layout.addWidget(self.view)

        grid = gl.GLGridItem()
        grid.scale(2, 2, 2)
        self.view.addItem(grid)

        self.boq_data = boq_data
        self.wall_height = wall_height
        self.scale = scale_ratio if scale_ratio is not None else 0.01

        self.vertexes = []
        self.faces = []
        self.colors = []

        self.build_architecture_mesh()

    def add_floor_texture(self, min_x, min_y, max_x, max_y, z_level, image_path):
        """Native PyQtGraph method to lay a tiled image flat on the floor."""
        if not os.path.exists(image_path): 
            print(f"Warning: {image_path} not found.")
            return
            
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is None: return
        
        # Ensure RGBA format
        if len(img.shape) == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGBA)
        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
        elif img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        
        width_m = max_x - min_x
        height_m = max_y - min_y
        if width_m <= 0 or height_m <= 0: return
        
        # Resize base image so tiling doesn't crash RAM, then tile it
        img = cv2.resize(img, (256, 256))
        repeats_x = max(1, int(width_m / 1.5))
        repeats_y = max(1, int(height_m / 1.5))
        img = np.tile(img, (repeats_y, repeats_x, 1))
        
        # Format for PyQtGraph (Flip Y, transpose to WxHxC)
        img = cv2.flip(img, 0)
        img_data = np.transpose(img, (1, 0, 2))
        
        item = gl.GLImageItem(img_data)
        item.scale(width_m / img_data.shape[0], height_m / img_data.shape[1], 1)
        item.translate(min_x, min_y, z_level)
        self.view.addItem(item)

    def add_vertical_texture(self, p1, p2, z_start, z_end, image_path):
        """Native PyQtGraph method to stand an image upright along a wall/door."""
        if not os.path.exists(image_path): return
        
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is None: return
        
        if len(img.shape) == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGBA)
        elif img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
        elif img.shape[2] == 4: img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        
        width_m = np.linalg.norm(np.array(p2) - np.array(p1))
        height_m = z_end - z_start
        if width_m <= 0 or height_m <= 0: return
        
        img = cv2.flip(img, 0)
        img_data = np.transpose(img, (1, 0, 2))
        
        item = gl.GLImageItem(img_data)
        item.scale(width_m / img_data.shape[0], height_m / img_data.shape[1], 1)
        
        # Stand the image upright (Rotate around X axis)
        item.rotate(90, 1, 0, 0)
        
        # Swivel the image to align perfectly with the wall's angle
        angle = np.degrees(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
        item.rotate(angle, 0, 0, 1)
        
        item.translate(p1[0], p1[1], z_start)
        self.view.addItem(item)

    def add_colored_polygon(self, pts_2d, z_start, z_end, color, expand_by=0.0):
        """Generates standard solid-color 3D geometry for walls and frames."""
        if len(pts_2d) < 2: return
        poly = Polygon(pts_2d)
        if not poly.is_valid or poly.area < 1e-4:
            poly = LineString(pts_2d).buffer(0.075 + expand_by, cap_style=2) 
        else:
            if not poly.is_valid: poly = poly.buffer(0)
            if expand_by > 0.0: poly = poly.buffer(expand_by, join_style=2)

        if poly.is_empty: return
        polys_to_process = poly.geoms if hasattr(poly, 'geoms') else [poly]

        for p in polys_to_process:
            coords = list(p.exterior.coords)
            
            # Sides
            for i in range(len(coords) - 1):
                p1, p2 = coords[i], coords[i + 1]
                v_offset = len(self.vertexes)
                self.vertexes.extend([
                    [p1[0], p1[1], z_start], [p2[0], p2[1], z_start],
                    [p2[0], p2[1], z_end], [p1[0], p1[1], z_end]
                ])
                self.faces.extend([
                    [v_offset, v_offset + 2, v_offset + 1],
                    [v_offset, v_offset + 3, v_offset + 2]
                ])
                self.colors.extend([color, color])

            # Caps
            try:
                tris = triangulate(p)
                buffered_p = p.buffer(1e-4) 
                for t in tris:
                    if buffered_p.covers(t.centroid):
                        t_coords = list(t.exterior.coords)[:3]
                        # Top
                        v_offset = len(self.vertexes)
                        self.vertexes.extend([
                            [t_coords[0][0], t_coords[0][1], z_end],
                            [t_coords[1][0], t_coords[1][1], z_end],
                            [t_coords[2][0], t_coords[2][1], z_end]
                        ])
                        self.faces.append([v_offset, v_offset + 2, v_offset + 1])
                        self.colors.append(color)
                        
                        # Bottom
                        v_offset = len(self.vertexes)
                        self.vertexes.extend([
                            [t_coords[0][0], t_coords[0][1], z_start],
                            [t_coords[1][0], t_coords[1][1], z_start],
                            [t_coords[2][0], t_coords[2][1], z_start]
                        ])
                        self.faces.append([v_offset, v_offset + 1, v_offset + 2])
                        self.colors.append(color)
            except Exception: pass

    def build_architecture_mesh(self):
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        # 1. Process Rooms & Walls
        for room in self.boq_data.get('rooms', []):
            raw_pts = room.get('points', [])
            if len(raw_pts) < 2: continue

            pts = [(pt[0] * self.scale, -pt[1] * self.scale) for pt in raw_pts]
            for x, y in pts:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)

            cid = room.get('class_id', -1)
            lbl = room.get('label', '')

            if cid == 2 or lbl == "Wall":
                self.add_colored_polygon(pts, 0.0, self.wall_height, [0.7, 0.7, 0.7, 1.0])
            elif cid == 8 or lbl == "Railing":
                self.add_colored_polygon(pts, 0.0, self.wall_height * 0.5, [0.5, 0.5, 0.5, 0.8])
            else:
                self.add_colored_polygon(pts, 0.0, 0.01, [0.2, 0.6, 1.0, 0.3])

        # 2. Process Items
        item_props = {
            1: (1.0, 2.2, [0.0, 0.8, 1.0, 0.4]),   
            3: (0.0, 2.5, [0.6, 0.4, 0.2, 1.0]),   
            4: (0.0, 0.9, [0.3, 0.3, 0.3, 1.0]),   
            5: (0.0, 0.5, [0.9, 0.9, 0.9, 1.0]),   
            6: (0.0, 0.9, [0.8, 0.8, 0.8, 1.0]),   
            7: (0.0, 0.5, [0.7, 0.5, 0.3, 1.0]),   
            8: (0.0, self.wall_height, [0.6, 0.2, 0.2, 1.0]), 
            9: (0.0, 0.6, [0.9, 0.9, 0.9, 1.0]),   
            10: (0.0, self.wall_height, [0.5, 0.5, 0.5, 1.0]) 
        }

        for icon in self.boq_data.get('icons', []):
            raw_pts = icon.get('points', [])
            if len(raw_pts) < 2: continue
            
            pts = [(pt[0] * self.scale, -pt[1] * self.scale) for pt in raw_pts]
            cid = icon.get('class_id', -1)
            
            if cid == 2: # Door
                # 1. Draw a solid dark brown core for the door thickness
                self.add_colored_polygon(pts, 0.0, 2.0, [0.3, 0.15, 0.05, 1.0], expand_by=0.01)
                
                # 2. Find the two longest edges of the rectangle (Front and Back faces)
                poly = Polygon(pts).buffer(0.012, join_style=2) # Slightly larger to prevent Z-fighting
                coords = list(poly.exterior.coords)
                edges = []
                for i in range(len(coords)-1):
                    p1, p2 = coords[i], coords[i+1]
                    dist = np.linalg.norm(np.array(p1)-np.array(p2))
                    edges.append((dist, p1, p2))
                
                # Sort by length and map the texture upright onto the two largest faces
                edges.sort(key=lambda x: x[0], reverse=True)
                for length, p1, p2 in edges[:2]:
                    if length > 0.1:
                        self.add_vertical_texture(p1, p2, 0.0, 2.0, "resources/door.jpg")
            else:
                props = item_props.get(cid, (0.0, 0.5, [1.0, 0.0, 0.0, 0.8]))
                self.add_colored_polygon(pts, props[0], props[1], props[2], expand_by=0.02)

        # 3. Base Floor
        if min_x != float('inf'):
            pad = max((max_x - min_x) * 0.05, 1.0) 
            
            # Dark gray concrete slab beneath everything
            floor_pts = [
                (min_x - pad, min_y - pad),
                (max_x + pad, min_y - pad),
                (max_x + pad, max_y + pad),
                (min_x - pad, max_y + pad)
            ]
            self.add_colored_polygon(floor_pts, -0.1, -0.01, [0.3, 0.3, 0.3, 1.0])
            
            # Textured floor sitting exactly on top of the slab
            #self.add_floor_texture(min_x - pad, min_y - pad, max_x + pad, max_y + pad, -0.01, "resources/floor.jpg")

        # 4. Render Main Mesh
        if self.vertexes:
            mesh = gl.GLMeshItem(
                vertexes=np.array(self.vertexes), 
                faces=np.array(self.faces), 
                faceColors=np.array(self.colors), 
                smooth=False, drawEdges=True, edgeColor=(0, 0, 0, 0.5) 
            )
            self.view.addItem(mesh)

            center = np.mean(np.array(self.vertexes), axis=0)
            self.view.opts['center'] = pyqtgraph.Vector(center[0], center[1], 0)
            self.view.setCameraPosition(distance=max(max_x - min_x, max_y - min_y) * 1.5)