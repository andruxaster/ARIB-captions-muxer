// capcheck — проверка выхода arib_caption_mux.py через libaribcaption
// (https://github.com/xqq/libaribcaption): вынимает PES субтитров из TS,
// декодирует их, печатает текст, тайминг, координаты и цвета, а с третьим
// аргументом ещё и рендерит каждую фразу в PNG (кадр 1920x1080).
//
// Сборка (Linux, нужны cmake, libfreetype-dev, libfontconfig-dev, libpng-dev
// и японский шрифт, например fonts-noto-cjk):
//   git clone https://github.com/xqq/libaribcaption && cd libaribcaption
//   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
//   L=$PWD; g++ -O2 -std=c++17 -I$L/include -I$L/build/include -I$L/src \
//     -I$L/test/png_writer/include capcheck.cpp $L/test/png_writer/png_writer.cpp \
//     $L/build/libaribcaption.a -lfreetype -lfontconfig -lpng -o capcheck
//
// Запуск:  ./capcheck out.m2t 0x130            # текст и параметры
//          ./capcheck out.m2t 0x130 pngdir     # + PNG: capNNN_ms_i_x_y.png
#include <cstdio>
#include <cstdint>
#include <vector>
#include <string>
#include "aribcaption/context.hpp"
#include "aribcaption/decoder.hpp"
#include "aribcaption/renderer.hpp"
#include "png_writer.hpp"
using namespace aribcaption;
int main(int argc,char**argv){
  if(argc<3){fprintf(stderr,"usage: capcheck ts pid [outdir]\n");return 1;}
  FILE*f=fopen(argv[1],"rb"); int want=strtol(argv[2],0,0); const char* outdir=argc>3?argv[3]:nullptr;
  Context ctx; ctx.SetLogcatCallback([](LogLevel l,const char*m){ if(l==LogLevel::kError) fprintf(stderr,"LOG: %s\n",m);});
  Decoder dec(ctx); dec.Initialize(EncodingScheme::kAuto, CaptionType::kCaption, Profile::kProfileA, LanguageId::kFirst);
  Renderer rend(ctx); if(outdir){ rend.Initialize(CaptionType::kCaption); rend.SetFrameSize(1920,1080);}
  {unsigned char b[1024]; size_t k=fread(b,1,1024,f); int o=0; for(o=0;o<188;o++) if(b[o]==0x47&&b[o+188]==0x47&&b[o+376]==0x47) break; fseek(f,o,SEEK_SET);}
  std::vector<uint8_t> pes; unsigned char p[188]; long n=0; int count=0; int lastcc=-1; long ccerr=0;
  auto flush=[&](){
    if(pes.size()<9) {pes.clear();return;}
    if(pes[0]||pes[1]||pes[2]!=1){fprintf(stderr,"bad pes start\n");pes.clear();return;}
    size_t plen=(pes[4]<<8)|pes[5]; if(pes.size()<6+plen){fprintf(stderr,"short PES %zu<%zu\n",pes.size(),6+plen);}
    int hl=pes[8]; int64_t pts=-1;
    if(pes[7]&0x80){auto h=&pes[9]; pts=((int64_t)(h[0]>>1)&7)<<30|h[1]<<22|(h[2]>>1)<<15|h[3]<<7|h[4]>>1;}
    const uint8_t* d=&pes[9+hl]; size_t len=6+plen-(9+hl);
    DecodeResult r; int64_t ms=pts*1000/90000;
    auto st=dec.Decode(d,len,ms,r);
    if(st==DecodeStatus::kGotCaption){
      auto&c=*r.caption; count++;
      printf("[%lld ms] flags=%u wait=%lld plane=%dx%d text=\"%s\"\n",(long long)ms,(unsigned)c.flags,(long long)c.wait_duration,c.plane_width,c.plane_height,c.text.c_str());
      for(auto&rg:c.regions){ auto&ch=rg.chars.front();
        printf("   region x=%d y=%d w=%d h=%d n=%zu fg=%02x%02x%02x%02x bg=%02x%02x%02x%02x scale=%.1f\n",rg.x,rg.y,rg.width,rg.height,rg.chars.size(),
          ch.text_color.r,ch.text_color.g,ch.text_color.b,ch.text_color.a,ch.back_color.r,ch.back_color.g,ch.back_color.b,ch.back_color.a,ch.char_horizontal_scale);}
      if(outdir){ rend.AppendCaption(c); RenderResult rr; auto rs=rend.Render(ms+1,rr);
        int i=0; for(auto&img:rr.images){ char fn[512]; snprintf(fn,sizeof fn,"%s/cap%03d_%lld_%d_%d_%d.png",outdir,count,(long long)ms,i++,img.dst_x,img.dst_y); png_writer_write_image(fn,img);} }
    } else if(st==DecodeStatus::kError) printf("[%lld ms] DECODE ERROR\n",(long long)ms);
    pes.clear();
  };
  while(fread(p,1,188,f)==188){ n++;
    if(p[0]!=0x47){fprintf(stderr,"sync\n");break;}
    int pid=((p[1]&0x1f)<<8)|p[2]; if(pid!=want) continue;
    int afc=(p[3]>>4)&3, cc=p[3]&15; if(afc&1){ if(lastcc>=0 && cc!=((lastcc+1)&15)) ccerr++; lastcc=cc; }
    int off=4; if(afc&2) off=5+p[4]; if(!(afc&1)||off>=188) continue;
    if(p[1]&0x40){ flush(); }
    pes.insert(pes.end(),p+off,p+188);
  }
  flush(); printf("captions: %d, cc errors: %ld\n",count,ccerr); return 0;
}
