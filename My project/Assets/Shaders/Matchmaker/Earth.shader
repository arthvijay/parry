// The matchmaker's Earth: the satellite map, lit by a sun, with a soft terminator, a
// glint on the oceans, city lights on the night side and atmospheric scattering at the
// limb. The map is looked up from the object-space normal, the same way the code places
// pins (u = atan2(x, -z), v = asin(y)), so a pin always sits on its city.
Shader "Matchmaker/Earth"
{
    Properties
    {
        _MainTex ("Day map", 2D) = "black" {}
        _SunDir ("Direction to the sun (world)", Vector) = (-0.6, 0.35, -0.7, 0)
        _Atmos ("Atmosphere", Color) = (0.42, 0.62, 1.0, 1)
        _City ("City lights", Color) = (1.0, 0.70, 0.36, 1)
        _Night ("Night side", Color) = (0.012, 0.016, 0.04, 1)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" "RenderPipeline"="UniversalPipeline" }
        Pass
        {
            Name "Earth"
            Tags { "LightMode"="UniversalForward" }
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"

            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _SunDir;
                float4 _Atmos;
                float4 _City;
                float4 _Night;
            CBUFFER_END

            struct Attributes { float4 positionOS : POSITION; float3 normalOS : NORMAL; };
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 objN : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
                float3 positionWS : TEXCOORD2;
            };

            Varyings vert(Attributes i)
            {
                Varyings o;
                VertexPositionInputs p = GetVertexPositionInputs(i.positionOS.xyz);
                o.positionCS = p.positionCS;
                o.positionWS = p.positionWS;
                o.objN = i.positionOS.xyz;
                o.normalWS = TransformObjectToWorldNormal(i.normalOS);
                return o;
            }

            float hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }

            half4 frag(Varyings i) : SV_Target
            {
                float3 n = normalize(i.objN);
                float u = atan2(n.x, -n.z) / (2.0 * PI) + 0.5;
                float v = asin(clamp(n.y, -1.0, 1.0)) / PI + 0.5;
                half3 c = SAMPLE_TEXTURE2D_LOD(_MainTex, sampler_MainTex, float2(u, v), 0).rgb;
                // Sea or land, judged on the map's own (sRGB) values: its seas are navy.
                float ocean = saturate((c.b - max(c.r, c.g)) * 6.0 - 0.15);
                #if !defined(UNITY_COLORSPACE_GAMMA)
                c = SRGBToLinear(c);   // the map is imported as linear data
                #endif

                float3 N = normalize(i.normalWS);
                float3 L = normalize(_SunDir.xyz);
                float3 V = normalize(GetWorldSpaceViewDir(i.positionWS));
                float ndl = dot(N, L);
                float day = smoothstep(-0.10, 0.30, ndl);

                half3 land = c * 1.45;
                half3 sea = lerp(half3(0.006, 0.03, 0.10), half3(0.02, 0.12, 0.30), saturate(ndl));
                half3 albedo = lerp(land, sea, ocean);
                half3 lit = albedo * (0.06 + 1.1 * saturate(ndl));
                float3 H = normalize(L + V);
                lit += pow(saturate(dot(N, H)), 140.0) * ocean * day * half3(1.0, 0.88, 0.72) * 0.18;

                // City lights: sparse, soft, round points on land, gathered into clusters
                // (a coarse noise picks where people live) and thinning towards the poles.
                float2 g = float2(u * 640.0, v * 320.0);
                float2 cell = floor(g);
                float2 inCell = frac(g) - 0.5;
                float point_ = saturate(1.0 - length(inCell) * 2.2);
                float lit_ = step(0.80, hash(cell));
                float region = smoothstep(0.45, 0.85, hash(floor(g * 0.06)));
                float lights = point_ * lit_ * region * (1.0 - ocean);
                lights *= 0.5 + 0.5 * hash(cell + 17.0);
                lights *= 1.0 - smoothstep(0.55, 0.78, abs(n.y));
                half3 night = _Night.rgb + _City.rgb * lights * 2.2;

                half3 col = lerp(night, lit, day);
                // Scattering at the limb, brighter on the sunlit side.
                float fres = pow(1.0 - saturate(dot(N, V)), 3.0);
                col += _Atmos.rgb * fres * (0.18 + 1.0 * saturate(ndl + 0.3));
                // A warm band along the terminator, the sunset seen from orbit.
                col += half3(1.0, 0.42, 0.22) * 0.12 * saturate(1.0 - abs(ndl) * 4.0);
                return half4(col, 1.0);
            }
            ENDHLSL
        }
    }
}
