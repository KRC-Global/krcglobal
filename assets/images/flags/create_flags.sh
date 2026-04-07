#!/bin/bash
# Script to create additional flag SVG files

cd "$(dirname "$0")"

# Nepal
cat > np.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#DC143C"/>
  <path d="M300,200 L700,500 L300,800 Z" fill="#003893"/>
  <polygon points="350,350 400,450 500,450 420,510 450,610 350,550 250,610 280,510 200,450 300,450" fill="#FFF"/>
</svg>
SVG

# Mongolia  
cat > mn.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#015197"/>
  <rect x="0" y="0" width="333" height="1000" fill="#C4272F"/>
  <rect x="667" y="0" width="333" height="1000" fill="#C4272F"/>
  <circle cx="167" cy="500" r="80" fill="#FCD116"/>
</svg>
SVG

# Pakistan
cat > pk.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#01411C"/>
  <rect x="0" y="0" width="250" height="1000" fill="#FFF"/>
  <circle cx="625" cy="500" r="150" fill="#FFF"/>
  <polygon points="625,350 675,475 800,475 700,550 750,675 625,600 500,675 550,550 450,475 575,475" fill="#FFF"/>
</svg>
SVG

# India
cat > in.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="333" fill="#FF9933"/>
  <rect y="667" width="1000" height="333" fill="#138808"/>
  <circle cx="500" cy="500" r="120" fill="none" stroke="#000080" stroke-width="8"/>
</svg>
SVG

# Ghana
cat > gh.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#006B3F"/>
  <rect y="0" width="1000" height="333" fill="#CE1126"/>
  <rect y="333" width="1000" height="334" fill="#FCD116"/>
  <polygon points="500,250 550,400 700,400 575,480 625,630 500,550 375,630 425,480 300,400 450,400" fill="#000"/>
</svg>
SVG

# Senegal
cat > sn.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FDEF42"/>
  <rect x="0" y="0" width="333" height="1000" fill="#00853F"/>
  <rect x="667" y="0" width="333" height="1000" fill="#E31B23"/>
  <polygon points="500,300 550,450 700,450 575,530 625,680 500,600 375,680 425,530 300,450 450,450" fill="#00853F"/>
</svg>
SVG

# Kenya
cat > ke.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="250" fill="#000"/>
  <rect y="250" width="1000" height="100" fill="#FFF"/>
  <rect y="350" width="1000" height="300" fill="#BB0000"/>
  <rect y="650" width="1000" height="100" fill="#FFF"/>
  <rect y="750" width="1000" height="250" fill="#006600"/>
  <ellipse cx="500" cy="500" rx="200" ry="120" fill="#FFF"/>
  <ellipse cx="500" cy="500" rx="180" ry="100" fill="#BB0000"/>
  <ellipse cx="500" cy="500" rx="160" ry="80" fill="#000"/>
</svg>
SVG

# Tanzania
cat > tz.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#00A3DD"/>
  <polygon points="0,0 1000,1000 1000,800 200,0" fill="#1EB53A"/>
  <polygon points="0,200 800,1000 1000,1000 0,0" fill="#1EB53A"/>
  <polygon points="0,0 1000,1000 1000,900 100,0" fill="#000"/>
  <polygon points="0,100 900,1000 1000,1000 0,0" fill="#000"/>
  <rect x="0" y="400" width="1414" height="200" fill="#FCD116" transform="rotate(45 500 500)"/>
</svg>
SVG

# Peru
cat > pe.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect x="0" y="0" width="333" height="1000" fill="#D91023"/>
  <rect x="667" y="0" width="333" height="1000" fill="#D91023"/>
</svg>
SVG

# Paraguay
cat > py.svg << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="333" fill="#D52B1E"/>
  <rect y="667" width="1000" height="333" fill="#0038A8"/>
  <circle cx="500" cy="500" r="120" fill="#FFFFFF" stroke="#0038A8" stroke-width="4"/>
  <polygon points="500,420 520,480 580,480 530,520 550,580 500,540 450,580 470,520 420,480 480,480" fill="#FCD116"/>
</svg>
SVG

