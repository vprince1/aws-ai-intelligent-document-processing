import os
import warnings

class LinearizeLayout:
    def __init__(self, 
                 j: dict, 
                 table_format: str = "grid", 
                 exclude_figure_text: bool=True,
                 exclude_page_header: bool=False, 
                 exclude_page_footer: bool=False, 
                 exclude_page_number: bool=False,
                 skip_table: bool=False,
                 save_txt_path: str=None, 
                 generate_markdown: bool=False):
        self.j = j
        self.table_format = table_format
        self.exclude_figure_text = exclude_figure_text
        self.exclude_page_header = exclude_page_header
        self.exclude_page_footer = exclude_page_footer
        self.exclude_page_number = exclude_page_number
        self.skip_table = skip_table
        self.save_txt_path = save_txt_path
        self.generate_markdown = generate_markdown
        
    def _get_layout_blocks(self) -> tuple:
        """Get all blocks of type 'LAYOUT' and a dictionary of Ids mapped to their corresponding block."""
        layouts = [x for x in self.j['Blocks'] if x['BlockType'].startswith('LAYOUT')]
        id2block = {x['Id']: x for x in self.j['Blocks']}
        return layouts, id2block

    def _geometry_match(self, geom1, geom2, tolerance=0.1):
        """Check if two geometries match within a given tolerance."""
        for key in ['Width', 'Height', 'Left', 'Top']:
            if abs(geom1[key] - geom2[key]) > tolerance:
                return False
        return True

    def _is_inside(self, inner_geom, outer_geom):
        """Check if inner geometry is fully contained within the outer geometry."""
        inner_left, inner_top, inner_right, inner_bottom = (
            inner_geom['Left'], 
            inner_geom['Top'], 
            inner_geom['Left'] + inner_geom['Width'], 
            inner_geom['Top'] + inner_geom['Height']
        )
        
        outer_left, outer_top, outer_right, outer_bottom = (
            outer_geom['Left'], 
            outer_geom['Top'], 
            outer_geom['Left'] + outer_geom['Width'], 
            outer_geom['Top'] + outer_geom['Height']
        )
        
        return (inner_left >= outer_left and inner_right <= outer_right and 
                inner_top >= outer_top and inner_bottom <= outer_bottom)
    
    def _validate_block_skip(self, blockType: str) -> bool:
        if self.exclude_page_header and blockType == "LAYOUT_HEADER":
            return True
        elif self.exclude_page_footer and blockType == "LAYOUT_FOOTER":
            return True
        elif self.exclude_page_number and blockType == "LAYOUT_PAGE_NUMBER":
            return True
        else:
            return False
    
    def _dfs(self, root, id2block):
        texts = []
        stack = [(root, 0)]
        while stack:
            block_id, depth = stack.pop()
            block = id2block[block_id]
            figure_geometries = [block['Geometry']['BoundingBox'] for block in self.j['Blocks'] if block['BlockType'] == 'LAYOUT_FIGURE']
            
            if self._validate_block_skip(block["BlockType"]):
                continue
            
            # Handle LAYOUT_TABLE type
            if not self.skip_table and block["BlockType"] == "LAYOUT_TABLE":
                table_data = []
                # Find the matching TABLE block for the LAYOUT_TABLE
                table_block = None
                for potential_table in [b for b in self.j['Blocks'] if b['BlockType'] == 'TABLE']:
                    if self._geometry_match(block['Geometry']['BoundingBox'], potential_table['Geometry']['BoundingBox']):
                        table_block = potential_table
                        break

                if table_block and "Relationships" in table_block:
                    table_content = {}
                    headers = {}
                    max_row = 0
                    max_col = 0
                    for cell_rel in table_block["Relationships"]:
                        if cell_rel['Type'] == "CHILD":
                            for cell_id in cell_rel['Ids']:
                                cell_block = id2block[cell_id]
                                if "Relationships" in cell_block:
                                    cell_text = " ".join([id2block[line_id]['Text'] for line_id in cell_block["Relationships"][0]['Ids']])
                                    row_idx = cell_block['RowIndex']
                                    col_idx = cell_block['ColumnIndex']
                                    max_row = max(max_row, row_idx)
                                    max_col = max(max_col, col_idx)
                                    for r in range(cell_block.get('RowSpan', 1)):
                                        for c in range(cell_block.get('ColumnSpan', 1)):
                                            if "EntityTypes" in cell_block and "COLUMN_HEADER" in cell_block["EntityTypes"]:
                                                headers[col_idx + c] = cell_text
                                            else:
                                                table_content[(row_idx + r, col_idx + c)] = cell_text
                    
                    table_data = []
                    start_row = 2 if headers else 1
                    for r in range(start_row, max_row + 1):
                        row_data = []
                        for c in range(1, max_col + 1):
                            row_data.append(table_content.get((r, c), ""))
                        table_data.append(row_data)

                    header_list = [headers.get(c, "") for c in range(1, max_col + 1)]
                
                    try:
                        from tabulate import tabulate
                    except ImportError:
                        raise ModuleNotFoundError(
                            "Could not import tabulate python package. "
                            "Please install it with `pip install tabulate`."
                        )                         
                    tab_fmt = "pipe" if self.generate_markdown else self.table_format
                    '''If Markdown is enabled then default to pipe for tables'''
                    texts.append(tabulate(table_data, headers=header_list, tablefmt=tab_fmt))
                    continue
                else:
                    warnings.warn("LAYOUT_TABLE detected but TABLES feature was not provided in API call. \
                                  Inlcuding TABLES feature may improve the layout output")
                    
            if block["BlockType"] == "LINE" and "Text" in block:
                if self.exclude_figure_text:
                    if any(self._is_inside(block['Geometry']['BoundingBox'], figure_geom) for figure_geom in figure_geometries):
                        continue
                texts += block['Text'],
            elif block["BlockType"] in ["LAYOUT_TITLE", "LAYOUT_SECTION_HEADER"] and "Relationships" in block:
                # Get the associated LINE text for the layout
                line_texts = [id2block[line_id]['Text'] for line_id in block["Relationships"][0]['Ids']]
                combined_text = ' '.join(line_texts)

                # Prefix with appropriate markdown
                if self.generate_markdown:
                    if block["BlockType"] == "LAYOUT_TITLE":
                        combined_text = f"# {combined_text}"
                    elif block["BlockType"] == "LAYOUT_SECTION_HEADER":
                        combined_text = f"## {combined_text}"

                texts += combined_text,
                
            if block["BlockType"].startswith('LAYOUT') and block["BlockType"] not in ["LAYOUT_TITLE", "LAYOUT_SECTION_HEADER"]:
                if "Relationships" in block:
                    relationships = block["Relationships"]
                    children = [(x, depth + 1) for x in relationships[0]['Ids']]            
                    stack.extend(reversed(children))
        return texts
    
    def _save_to_files(self, page_texts: dict) -> None:
        path = self.save_txt_path.rstrip(os.sep)
        for page_number, content in page_texts.items():            
            file_path = os.path.join(path, f"{page_number}.txt")
            print(f"Writing page {page_number} in file {file_path}")
            with open(file_path, "w") as f:
                f.write(content)
                
    def get_text(self) -> dict:
        """Retrieve the text content in specified format. Default is CSV. Options: "csv", "markdown"."""
        # texts = []
        page_texts = {}
        layouts, id2block = self._get_layout_blocks()
        for layout in layouts:
            root = layout['Id']
            page_number = layout.get('Page', 1)
            if page_number not in page_texts:
                page_texts[page_number] = ""
            page_texts[page_number] += '\n'.join(self._dfs(root, id2block))+ "\n\n"
        if self.save_txt_path:
            self._save_to_files(page_texts)
        return page_texts
