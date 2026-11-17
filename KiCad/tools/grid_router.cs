using System;
using System.Collections.Generic;
public static class GridRouter {
    struct Item { public int Id; public float G,F; public Item(int i,float g,float f){Id=i;G=g;F=f;} }
    class Heap {
        List<Item> a=new List<Item>();
        public int Count {get{return a.Count;}}
        public void Push(Item v){a.Add(v);int i=a.Count-1;while(i>0){int p=(i-1)/2;if(a[p].F<=v.F)break;a[i]=a[p];i=p;}a[i]=v;}
        public Item Pop(){Item r=a[0],v=a[a.Count-1];a.RemoveAt(a.Count-1);if(a.Count==0)return r;int i=0;while(i*2+1<a.Count){int j=i*2+1;if(j+1<a.Count&&a[j+1].F<a[j].F)j++;if(a[j].F>=v.F)break;a[i]=a[j];i=j;}a[i]=v;return r;}
    }
    static float Heur(int x,int y,int ex,int ey){int dx=Math.Abs(x-ex),dy=Math.Abs(y-ey);return Math.Max(dx,dy)+.41421356f*Math.Min(dx,dy);}
    public static int[] SolveLayers(byte[] mask,byte[] via,int w,int h,int start,int[] ends,int preferred){
        int plane=w*h,n=plane*2;if(mask[start]!=0)return new int[0];
        bool[] goal=new bool[n],closed=new bool[n];int ex=0,ey=0;float best=float.MaxValue;
        int sx=start%plane%w,sy=start%plane/w;
        foreach(int e in ends){if(e<0||e>=n||mask[e]!=0)continue;goal[e]=true;float v=Heur(sx,sy,e%plane%w,e%plane/w);if(v<best){best=v;ex=e%plane%w;ey=e%plane/w;}}
        if(best==float.MaxValue)return new int[0];
        float[] scores=new float[n];int[] parent=new int[n];for(int i=0;i<n;i++)scores[i]=float.MaxValue;
        scores[start]=0;Heap heap=new Heap();heap.Push(new Item(start,0,best));
        int[] dxs={-1,1,0,0,-1,1,-1,1},dys={0,0,-1,1,-1,1,1,-1};
        while(heap.Count>0){Item item=heap.Pop();int u=item.Id;if(closed[u])continue;
            if(goal[u]){List<int> path=new List<int>();path.Add(u);while(u!=start){u=parent[u];path.Add(u);}path.Reverse();return path.ToArray();}
            closed[u]=true;int layer=u/plane,local=u%plane,x=local%w,y=local/w;
            for(int i=0;i<9;i++){int v;float extra;
                if(i==8){if(via[local]!=0)continue;v=(1-layer)*plane+local;if(mask[v]!=0||closed[v])continue;extra=80;}
                else {int dx=dxs[i],dy=dys[i],xx=x+dx,yy=y+dy;if(xx<0||xx>=w||yy<0||yy>=h)continue;
                    v=layer*plane+yy*w+xx;if(mask[v]!=0||closed[v])continue;if(dx!=0&&dy!=0&&(mask[layer*plane+y*w+xx]!=0||mask[layer*plane+yy*w+x]!=0))continue;
                    extra=(i<4?1:1.41421356f)*(layer==preferred?1:12);
                }
                float nc=item.G+extra;if(nc<scores[v]){scores[v]=nc;parent[v]=u;heap.Push(new Item(v,nc,nc+1.1f*Heur(v%plane%w,v%plane/w,ex,ey)));}
            }
        }
        return new int[0];
    }
    public static int[] Solve(byte[] mask,byte[] heat,int w,int h,int start,int[] ends){
        int n=w*h;if(mask[start]!=0)return new int[0];
        bool[] goal=new bool[n],closed=new bool[n];int ex=0,ey=0;float best=float.MaxValue;
        int sx=start%w,sy=start/w;
        foreach(int e in ends){if(e<0||e>=n||mask[e]!=0)continue;goal[e]=true;float v=Heur(sx,sy,e%w,e/w);if(v<best){best=v;ex=e%w;ey=e/w;}}
        if(best==float.MaxValue)return new int[0];
        float[] scores=new float[n];int[] parent=new int[n];for(int i=0;i<n;i++)scores[i]=float.MaxValue;
        scores[start]=0;Heap heap=new Heap();heap.Push(new Item(start,0,best));
        int[] dxs={-1,1,0,0,-1,1,-1,1},dys={0,0,-1,1,-1,1,1,-1};
        while(heap.Count>0){Item item=heap.Pop();int u=item.Id;if(closed[u])continue;
            if(goal[u]){List<int> path=new List<int>();path.Add(u);while(u!=start){u=parent[u];path.Add(u);}path.Reverse();return path.ToArray();}
            closed[u]=true;int x=u%w,y=u/w;
            for(int i=0;i<8;i++){int dx=dxs[i],dy=dys[i],xx=x+dx,yy=y+dy;if(xx<0||xx>=w||yy<0||yy>=h)continue;
                int v=yy*w+xx;if(mask[v]!=0||closed[v])continue;if(dx!=0&&dy!=0&&(mask[y*w+xx]!=0||mask[yy*w+x]!=0))continue;
                float nc=item.G+(i<4?1:1.41421356f)+(heat.Length>0?heat[v]*10:0);if(nc<scores[v]){scores[v]=nc;parent[v]=u;heap.Push(new Item(v,nc,nc+1.05f*Heur(xx,yy,ex,ey)));}
            }
        }
        return new int[0];
    }
}
