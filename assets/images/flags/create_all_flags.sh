#!/bin/bash
# 모든 국가 국기 SVG 생성

# 브루나이 (Brunei)
cat > bn.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#F7E017"/>
  <polygon points="0,0 0,1000 1000,500" fill="#000"/>
  <polygon points="1000,0 1000,1000 0,500" fill="#FFF"/>
  <circle cx="500" cy="500" r="150" fill="#CE1126" stroke="#000" stroke-width="3"/>
</svg>
EOF

# 우즈베키스탄
cat > uz.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="333" fill="#1EB53A"/>
  <rect y="333" width="1000" height="30" fill="#CE1126"/>
  <rect y="363" width="1000" height="274" fill="#FFF"/>
  <rect y="637" width="1000" height="30" fill="#CE1126"/>
  <rect y="667" width="1000" height="333" fill="#0099B5"/>
  <circle cx="200" cy="200" r="80" fill="#FFF"/>
  <polygon points="200,140 220,190 275,190 230,225 250,275 200,240 150,275 170,225 125,190 180,190" fill="#FFF"/>
</svg>
EOF

# 키르기스스탄
cat > kg.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#E8112D"/>
  <circle cx="500" cy="500" r="180" fill="#FFEF00"/>
  <circle cx="500" cy="500" r="140" fill="#E8112D"/>
</svg>
EOF

# 카자흐스탄
cat > kz.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#00AFCA"/>
  <circle cx="700" cy="300" r="90" fill="#FEC50C"/>
  <polygon points="500,200 530,340 670,340 560,420 590,560 500,480 410,560 440,420 330,340 470,340" fill="#FEC50C"/>
</svg>
EOF

# 모잠비크
cat > mz.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="250" fill="#007168"/>
  <rect y="250" width="1000" height="60" fill="#FFF"/>
  <rect y="310" width="1000" height="90" fill="#000"/>
  <rect y="400" width="1000" height="200" fill="#FCE100"/>
  <rect y="600" width="1000" height="90" fill="#000"/>
  <rect y="690" width="1000" height="60" fill="#FFF"/>
  <rect y="750" width="1000" height="250" fill="#D90000"/>
  <polygon points="0,0 0,1000 500,500" fill="#D90000"/>
  <polygon points="250,500 280,550 340,550 290,585 310,635 250,600 190,635 210,585 160,550 220,550" fill="#FCE100"/>
</svg>
EOF

# 감비아
cat > gm.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#3A7728"/>
  <rect y="0" width="1000" height="300" fill="#CE1126"/>
  <rect y="300" width="1000" height="100" fill="#FFF"/>
  <rect y="400" width="1000" height="200" fill="#0C1C8C"/>
  <rect y="600" width="1000" height="100" fill="#FFF"/>
  <rect y="700" width="1000" height="300" fill="#3A7728"/>
</svg>
EOF

# 기니
cat > gn.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#009460"/>
  <rect x="0" y="0" width="333" height="1000" fill="#CE1126"/>
  <rect x="333" y="0" width="334" height="1000" fill="#FCD116"/>
  <rect x="667" y="0" width="333" height="1000" fill="#009460"/>
</svg>
EOF

# 말라위
cat > mw.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#339E35"/>
  <rect y="0" width="1000" height="333" fill="#000"/>
  <rect y="333" width="1000" height="334" fill="#CE1126"/>
  <rect y="667" width="1000" height="333" fill="#339E35"/>
  <circle cx="500" cy="200" r="80" fill="#CE1126"/>
</svg>
EOF

# 카메룬
cat > cm.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FCD116"/>
  <rect x="0" y="0" width="333" height="1000" fill="#007A5E"/>
  <rect x="667" y="0" width="333" height="1000" fill="#CE1126"/>
  <polygon points="500,300 530,440 670,440 560,520 590,660 500,580 410,660 440,520 330,440 470,440" fill="#FCD116"/>
</svg>
EOF

# 우간다
cat > ug.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#D90000"/>
  <rect y="0" width="1000" height="143" fill="#000"/>
  <rect y="143" width="1000" height="143" fill="#FCDC04"/>
  <rect y="286" width="1000" height="143" fill="#D90000"/>
  <rect y="429" width="1000" height="142" fill="#000"/>
  <rect y="571" width="1000" height="143" fill="#FCDC04"/>
  <rect y="714" width="1000" height="143" fill="#D90000"/>
  <rect y="857" width="1000" height="143" fill="#000"/>
  <circle cx="500" cy="500" r="200" fill="#FFF"/>
  <circle cx="500" cy="500" r="150" fill="#000"/>
</svg>
EOF

# 코트디부아르
cat > ci.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#009E60"/>
  <rect x="0" y="0" width="333" height="1000" fill="#F77F00"/>
  <rect x="333" y="0" width="334" height="1000" fill="#FFF"/>
  <rect x="667" y="0" width="333" height="1000" fill="#009E60"/>
</svg>
EOF

# DR콩고
cat > cd.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#007FFF"/>
  <path d="M0,0 L1000,1000" stroke="#F7D618" stroke-width="50"/>
  <path d="M0,0 L1000,1000" stroke="#CE1126" stroke-width="30"/>
  <polygon points="200,150 220,210 285,210 235,250 255,310 200,270 145,310 165,250 115,210 180,210" fill="#F7D618"/>
</svg>
EOF

# 알제리
cat > dz.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect x="0" y="0" width="500" height="1000" fill="#007229"/>
  <circle cx="600" cy="500" r="180" fill="#D21034"/>
  <circle cx="650" cy="500" r="140" fill="#FFF"/>
  <polygon points="600,380 620,440 685,440 635,480 655,540 600,500 545,540 565,480 515,440 580,440" fill="#D21034"/>
</svg>
EOF

# 요르단
cat > jo.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#007A3D"/>
  <rect y="0" width="1000" height="333" fill="#000"/>
  <rect y="333" width="1000" height="334" fill="#FFF"/>
  <rect y="667" width="1000" height="333" fill="#007A3D"/>
  <polygon points="0,0 0,1000 500,500" fill="#CE1126"/>
  <polygon points="150,500 165,530 200,530 172,552 184,582 150,560 116,582 128,552 100,530 135,530" fill="#FFF"/>
</svg>
EOF

# 아르헨티나
cat > ar.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="333" fill="#74ACDF"/>
  <rect y="667" width="1000" height="333" fill="#74ACDF"/>
  <circle cx="500" cy="500" r="120" fill="#F6B40E"/>
  <circle cx="500" cy="500" r="80" fill="none" stroke="#8B4513" stroke-width="8"/>
</svg>
EOF

# 볼리비아
cat > bo.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#007934"/>
  <rect y="0" width="1000" height="333" fill="#D52B1E"/>
  <rect y="333" width="1000" height="334" fill="#F9E300"/>
  <rect y="667" width="1000" height="333" fill="#007934"/>
</svg>
EOF

# 과테말라
cat > gt.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect x="0" y="0" width="333" height="1000" fill="#4997D0"/>
  <rect x="667" y="0" width="333" height="1000" fill="#4997D0"/>
</svg>
EOF

# 엘살바도르
cat > sv.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="333" fill="#0F47AF"/>
  <rect y="667" width="1000" height="333" fill="#0F47AF"/>
</svg>
EOF

# 키리바시
cat > ki.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#FFF"/>
  <rect y="0" width="1000" height="500" fill="#E73E2C"/>
  <rect y="500" width="1000" height="167" fill="#FFC639"/>
  <rect y="667" width="1000" height="167" fill="#FFF"/>
  <rect y="834" width="1000" height="166" fill="#003F87"/>
</svg>
EOF

# 러시아
cat > ru.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#D52B1E"/>
  <rect y="0" width="1000" height="333" fill="#FFF"/>
  <rect y="333" width="1000" height="334" fill="#0039A6"/>
  <rect y="667" width="1000" height="333" fill="#D52B1E"/>
</svg>
EOF

# 이란
cat > ir.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#DA0000"/>
  <rect y="0" width="1000" height="333" fill="#239F40"/>
  <rect y="333" width="1000" height="334" fill="#FFF"/>
  <rect y="667" width="1000" height="333" fill="#DA0000"/>
  <circle cx="500" cy="500" r="100" fill="none" stroke="#DA0000" stroke-width="8"/>
</svg>
EOF

# 아프가니스탄
cat > af.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#007A36"/>
  <rect x="0" y="0" width="333" height="1000" fill="#000"/>
  <rect x="333" y="0" width="334" height="1000" fill="#D32011"/>
  <rect x="667" y="0" width="333" height="1000" fill="#007A36"/>
</svg>
EOF

# 중국 코드 추가
cat > cn.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
  <circle cx="500" cy="500" r="500" fill="#DE2910"/>
  <polygon points="200,200 240,340 390,340 270,430 310,570 200,480 90,570 130,430 10,340 160,340" fill="#FFDE00"/>
  <polygon points="420,180 430,210 465,210 435,230 445,260 420,240 395,260 405,230 375,210 410,210" fill="#FFDE00"/>
  <polygon points="480,270 490,300 525,300 495,320 505,350 480,330 455,350 465,320 435,300 470,300" fill="#FFDE00"/>
  <polygon points="480,390 490,420 525,420 495,440 505,470 480,450 455,470 465,440 435,420 470,420" fill="#FFDE00"/>
  <polygon points="420,480 430,510 465,510 435,530 445,560 420,540 395,560 405,530 375,510 410,510" fill="#FFDE00"/>
</svg>
EOF

echo "모든 국기 SVG 파일이 생성되었습니다."
