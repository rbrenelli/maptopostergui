import osmnx as ox
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
import matplotlib.colors as mcolors
import numpy as np
from geopy.geocoders import Nominatim
import time
import json
import os
import sys
from datetime import datetime

class MapGenerator:
    def __init__(self, themes_dir="themes", fonts_dir="fonts", posters_dir="posters"):
        # Handle path for frozen application (PyInstaller)
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        self.themes_dir = os.path.join(base_path, themes_dir)
        self.fonts_dir = os.path.join(base_path, fonts_dir)

        # Posters should remain in user's working directory or home directory
        # Using current working directory for now as per original design,
        # but robust apps might use user's documents.
        self.posters_dir = posters_dir

        self.fonts = self.load_fonts()

        # Create directories if they don't exist
        # We only create themes/fonts dir if we are NOT frozen (dev mode)
        # In frozen mode, they are read-only in temp dir.
        if not getattr(sys, 'frozen', False):
            for d in [self.themes_dir, self.fonts_dir]:
                if not os.path.exists(d):
                    os.makedirs(d)

        if not os.path.exists(self.posters_dir):
            os.makedirs(self.posters_dir)

    def load_fonts(self):
        """
        Load Roboto fonts from the fonts directory.
        Returns dict with font paths for different weights.
        """
        fonts = {
            'bold': os.path.join(self.fonts_dir, 'Roboto-Bold.ttf'),
            'regular': os.path.join(self.fonts_dir, 'Roboto-Regular.ttf'),
            'light': os.path.join(self.fonts_dir, 'Roboto-Light.ttf')
        }

        # Verify fonts exist
        for weight, path in fonts.items():
            if not os.path.exists(path):
                # Only warn if not running in a context where we expect them missing (like initial setup)
                # print(f"⚠ Font not found: {path}")
                pass

        return fonts

    def get_available_themes(self):
        """
        Scans the themes directory and returns a list of available theme names.
        """
        if not os.path.exists(self.themes_dir):
            if not getattr(sys, 'frozen', False):
                os.makedirs(self.themes_dir)
            return []

        themes = []
        for file in sorted(os.listdir(self.themes_dir)):
            if file.endswith('.json'):
                theme_name = file[:-5]  # Remove .json extension
                themes.append(theme_name)
        return themes

    def load_theme(self, theme_name="feature_based"):
        """
        Load theme from JSON file in themes directory.
        """
        theme_file = os.path.join(self.themes_dir, f"{theme_name}.json")

        if not os.path.exists(theme_file):
            print(f"⚠ Theme file '{theme_file}' not found. Using default feature_based theme.")
            # Fallback to embedded default theme
            return {
                "name": "Feature-Based Shading",
                "bg": "#FFFFFF",
                "text": "#000000",
                "gradient_color": "#FFFFFF",
                "water": "#C0C0C0",
                "parks": "#F0F0F0",
                "road_motorway": "#0A0A0A",
                "road_primary": "#1A1A1A",
                "road_secondary": "#2A2A2A",
                "road_tertiary": "#3A3A3A",
                "road_residential": "#4A4A4A",
                "road_default": "#3A3A3A"
            }

        with open(theme_file, 'r') as f:
            theme = json.load(f)
            return theme

    def get_coordinates(self, city, country):
        """
        Fetches coordinates for a given city and country using geopy.
        """
        print(f"Looking up coordinates for {city}, {country}...")
        geolocator = Nominatim(user_agent="city_map_poster_gui")

        # Add a small delay
        time.sleep(1)

        location = geolocator.geocode(f"{city}, {country}")

        if location:
            print(f"✓ Found: {location.address}")
            print(f"✓ Coordinates: {location.latitude}, {location.longitude}")
            return (location.latitude, location.longitude)
        else:
            raise ValueError(f"Could not find coordinates for {city}, {country}")

    def fetch_data(self, point, dist, callback=None):
        """
        Fetches map data (streets, water, parks) from OSMnx.
        Optionally accepts a callback function to report progress (string, float 0-1).
        """
        data = {}

        # 1. Fetch Street Network
        if callback: callback("Downloading street network...", 0.1)
        data['G'] = ox.graph_from_point(point, dist=dist, dist_type='bbox', network_type='all')
        time.sleep(0.5)  # Rate limit

        # 2. Fetch Water Features
        if callback: callback("Downloading water features...", 0.4)
        try:
            data['water'] = ox.features_from_point(point, tags={'natural': 'water', 'waterway': 'riverbank'}, dist=dist)
        except Exception:
            data['water'] = None
        time.sleep(0.3)

        # 3. Fetch Parks
        if callback: callback("Downloading parks/green spaces...", 0.7)
        try:
            data['parks'] = ox.features_from_point(point, tags={'leisure': 'park', 'landuse': 'grass'}, dist=dist)
        except Exception:
            data['parks'] = None

        if callback: callback("Data fetch complete", 1.0)
        return data

    def _create_gradient_fade(self, ax, color, location='bottom', zorder=10):
        vals = np.linspace(0, 1, 256).reshape(-1, 1)
        gradient = np.hstack((vals, vals))

        rgb = mcolors.to_rgb(color)
        my_colors = np.zeros((256, 4))
        my_colors[:, 0] = rgb[0]
        my_colors[:, 1] = rgb[1]
        my_colors[:, 2] = rgb[2]

        if location == 'bottom':
            my_colors[:, 3] = np.linspace(1, 0, 256)
            extent_y_start = 0
            extent_y_end = 0.25
        else:
            my_colors[:, 3] = np.linspace(0, 1, 256)
            extent_y_start = 0.75
            extent_y_end = 1.0

        custom_cmap = mcolors.ListedColormap(my_colors)

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        y_range = ylim[1] - ylim[0]

        y_bottom = ylim[0] + y_range * extent_y_start
        y_top = ylim[0] + y_range * extent_y_end

        ax.imshow(gradient, extent=[xlim[0], xlim[1], y_bottom, y_top],
                  aspect='auto', cmap=custom_cmap, zorder=zorder, origin='lower')

    def _get_edge_colors_by_type(self, G, theme):
        edge_colors = []
        for u, v, data in G.edges(data=True):
            highway = data.get('highway', 'unclassified')
            if isinstance(highway, list):
                highway = highway[0] if highway else 'unclassified'

            if highway in ['motorway', 'motorway_link']:
                color = theme['road_motorway']
            elif highway in ['trunk', 'trunk_link', 'primary', 'primary_link']:
                color = theme['road_primary']
            elif highway in ['secondary', 'secondary_link']:
                color = theme['road_secondary']
            elif highway in ['tertiary', 'tertiary_link']:
                color = theme['road_tertiary']
            elif highway in ['residential', 'living_street', 'unclassified']:
                color = theme['road_residential']
            else:
                color = theme['road_default']
            edge_colors.append(color)
        return edge_colors

    def _get_edge_widths_by_type(self, G):
        edge_widths = []
        for u, v, data in G.edges(data=True):
            highway = data.get('highway', 'unclassified')
            if isinstance(highway, list):
                highway = highway[0] if highway else 'unclassified'

            if highway in ['motorway', 'motorway_link']:
                width = 1.2
            elif highway in ['trunk', 'trunk_link', 'primary', 'primary_link']:
                width = 1.0
            elif highway in ['secondary', 'secondary_link']:
                width = 0.8
            elif highway in ['tertiary', 'tertiary_link']:
                width = 0.6
            else:
                width = 0.4
            edge_widths.append(width)
        return edge_widths

    def render_map(self, data, theme, city, country, point):
        """
        Renders the map and returns the matplotlib Figure object.
        """
        G = data['G']
        water = data['water']
        parks = data['parks']

        # Thread-safe figure creation
        fig = Figure(figsize=(12, 16), facecolor=theme['bg'])
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(theme['bg'])

        # Layer 1: Polygons
        if water is not None and not water.empty:
            water.plot(ax=ax, facecolor=theme['water'], edgecolor='none', zorder=1)
        if parks is not None and not parks.empty:
            parks.plot(ax=ax, facecolor=theme['parks'], edgecolor='none', zorder=2)

        # Layer 2: Roads
        edge_colors = self._get_edge_colors_by_type(G, theme)
        edge_widths = self._get_edge_widths_by_type(G)

        ox.plot_graph(
            G, ax=ax, bgcolor=theme['bg'],
            node_size=0,
            edge_color=edge_colors,
            edge_linewidth=edge_widths,
            show=False, close=False
        )

        # Layer 3: Gradients
        self._create_gradient_fade(ax, theme['gradient_color'], location='bottom', zorder=10)
        self._create_gradient_fade(ax, theme['gradient_color'], location='top', zorder=10)

        # 4. Typography
        if self.fonts and os.path.exists(self.fonts['bold']):
             font_main = FontProperties(fname=self.fonts['bold'], size=60)
             font_top = FontProperties(fname=self.fonts['bold'], size=40)
             font_sub = FontProperties(fname=self.fonts['light'], size=22)
             font_coords = FontProperties(fname=self.fonts['regular'], size=14)
             font_attr = FontProperties(fname=self.fonts['light'], size=8)
        else:
             font_main = FontProperties(family='monospace', weight='bold', size=60)
             font_top = FontProperties(family='monospace', weight='bold', size=40)
             font_sub = FontProperties(family='monospace', weight='normal', size=22)
             font_coords = FontProperties(family='monospace', size=14)
             font_attr = FontProperties(family='monospace', size=8)

        spaced_city = "  ".join(list(city.upper()))

        # Bottom Text
        ax.text(0.5, 0.14, spaced_city, transform=ax.transAxes,
                color=theme['text'], ha='center', fontproperties=font_main, zorder=11)

        ax.text(0.5, 0.10, country.upper(), transform=ax.transAxes,
                color=theme['text'], ha='center', fontproperties=font_sub, zorder=11)

        lat, lon = point
        coords = f"{lat:.4f}° N / {lon:.4f}° E" if lat >= 0 else f"{abs(lat):.4f}° S / {lon:.4f}° E"
        if lon < 0:
            coords = coords.replace("E", "W")

        ax.text(0.5, 0.07, coords, transform=ax.transAxes,
                color=theme['text'], alpha=0.7, ha='center', fontproperties=font_coords, zorder=11)

        ax.plot([0.4, 0.6], [0.125, 0.125], transform=ax.transAxes,
                color=theme['text'], linewidth=1, zorder=11)

        # Attribution
        ax.text(0.98, 0.02, "© OpenStreetMap contributors", transform=ax.transAxes,
                color=theme['text'], alpha=0.5, ha='right', va='bottom',
                fontproperties=font_attr, zorder=11)

        return fig

    def save_poster(self, fig, output_file, dpi=300):
        """
        Saves the figure to a file.
        """
        print(f"Saving to {output_file}...")
        # Get background color from figure for saving
        bg_color = fig.get_facecolor()
        fig.savefig(output_file, dpi=dpi, facecolor=bg_color)
        print(f"✓ Done! Poster saved as {output_file}")

    def generate_output_filename(self, city, theme_name):
        """
        Generate unique output filename.
        """
        if not os.path.exists(self.posters_dir):
            os.makedirs(self.posters_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        city_slug = city.lower().replace(' ', '_')
        filename = f"{city_slug}_{theme_name}_{timestamp}.png"
        return os.path.join(self.posters_dir, filename)
