// Recolours the clothing painted into a Rocketbox body texture, keeping the skin.
// Used once per texture through Graphics.Blit by AvatarTinter; never drawn in a scene.
Shader "Hidden/Parry/OutfitRecolor"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _Cloth ("Cloth colour", Color) = (0.02, 0.02, 0.025, 1)
        _Fold ("Fold detail kept", Range(0, 1)) = 0.12
    }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float4 _Cloth;
            float _Fold;

            float3 hsv(float3 c)
            {
                float4 K = float4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
                float4 p = lerp(float4(c.bg, K.wz), float4(c.gb, K.xy), step(c.b, c.g));
                float4 q = lerp(float4(p.xyw, c.r), float4(c.r, p.yzx), step(p.x, c.r));
                float d = q.x - min(q.w, q.y);
                return float3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-5)), d / (q.x + 1e-5), q.x);
            }

            fixed4 frag(v2f_img i) : SV_Target
            {
                fixed4 src = tex2D(_MainTex, i.uv);
                float3 c = src.rgb;
            #ifndef UNITY_COLORSPACE_GAMMA
                c = LinearToGammaSpace(c);
            #endif
                float3 h = hsv(c);
                // Skin: warm hue, some saturation, not dark. Everything else is clothing.
                float skin = step(h.x, 0.11) * step(0.14, h.y) * step(h.y, 0.70) * step(0.52, h.z);
                skin = max(skin, step(0.93, h.x) * step(0.14, h.y) * step(0.52, h.z));
                // Black fabric that keeps the folds of the original, with a faint satin lift.
                float lum = dot(c, float3(0.299, 0.587, 0.114));
                float3 cloth = _Cloth.rgb + _Fold * pow(lum, 1.6);
                float3 o = lerp(cloth, c, skin);
            #ifndef UNITY_COLORSPACE_GAMMA
                o = GammaToLinearSpace(o);
            #endif
                return fixed4(o, src.a);
            }
            ENDCG
        }
    }
}
