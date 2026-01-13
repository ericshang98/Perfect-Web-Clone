"use client";

import Image from "next/image";
import Link from "next/link";
import { Sparkles, Github, Twitter } from "lucide-react";
import { cn } from "@/lib/utils";

interface FooterProps {
  brand?: {
    name: string;
    logo?: string;
    description?: string;
  };
  nav?: Array<{
    title: string;
    children: Array<{
      title: string;
      url: string;
    }>;
  }>;
  social?: Array<{
    icon: string;
    url: string;
    title?: string;
  }>;
  copyright?: string;
  className?: string;
}

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  Github,
  Twitter,
};

export function Footer({ brand, nav, social, copyright, className }: FooterProps) {
  return (
    <footer className={cn("py-8 sm:py-8 overflow-x-hidden", className)}>
      <div className="container space-y-8 overflow-x-hidden">
        <div className="grid min-w-0 gap-12 md:grid-cols-5">
          <div className="min-w-0 space-y-4 break-words md:col-span-2 md:space-y-6">
            <Link href="/" className="flex items-center gap-2">
              {brand?.logo ? (
                brand.logo === "/logo.svg" ? (
                  <>
                    {/* Light mode logo */}
                    <Image
                      src="/logo-for-light.svg"
                      alt={brand.name || "Logo"}
                      width={140}
                      height={38}
                      className="h-9 w-auto dark:hidden"
                      unoptimized
                    />
                    {/* Dark mode logo */}
                    <Image
                      src="/logo-for-dark.svg"
                      alt={brand.name || "Logo"}
                      width={140}
                      height={38}
                      className="h-9 w-auto hidden dark:block"
                      unoptimized
                    />
                  </>
                ) : (
                  <Image
                    src={brand.logo}
                    alt={brand.name || "Logo"}
                    width={140}
                    height={38}
                    className="h-9 w-auto"
                  />
                )
              ) : (
                <>
                  <div className="flex size-8 items-center justify-center rounded-lg bg-primary">
                    <Sparkles className="size-4 text-primary-foreground" />
                  </div>
                  <span className="text-lg font-semibold">{brand?.name || "Perfect Clone"}</span>
                </>
              )}
            </Link>

            {brand?.description && (
              <p className="text-muted-foreground text-sm text-balance break-words">
                {brand.description}
              </p>
            )}
          </div>

          <div className="col-span-3 grid min-w-0 gap-6 sm:grid-cols-3">
            {nav?.map((item, idx) => (
              <div key={idx} className="min-w-0 space-y-4 text-sm break-words">
                <span className="block font-medium break-words">{item.title}</span>
                <div className="flex min-w-0 flex-wrap gap-4 sm:flex-col">
                  {item.children?.map((subItem, iidx) => (
                    <Link
                      key={iidx}
                      href={subItem.url}
                      className="text-muted-foreground hover:text-primary block break-words duration-150"
                    >
                      <span className="break-words">{subItem.title}</span>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div
          aria-hidden
          className="h-px min-w-0 [background-image:linear-gradient(90deg,var(--color-foreground)_1px,transparent_1px)] bg-[length:6px_1px] bg-repeat-x opacity-25"
        />

        <div className="flex min-w-0 flex-wrap justify-between gap-8">
          <p className="text-muted-foreground text-sm text-balance break-words">
            {copyright || `© ${new Date().getFullYear()} ${brand?.name || "Nexting"}. All rights reserved.`}
          </p>

          <div className="min-w-0 flex-1" />

          {social && social.length > 0 && (
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {social.map((item, index) => {
                const Icon = iconMap[item.icon] || Github;
                return (
                  <Link
                    key={index}
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-muted-foreground hover:text-primary bg-background block cursor-pointer rounded-full p-2 duration-150"
                    aria-label={item.title || "Social media link"}
                  >
                    <Icon className="size-5" />
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </footer>
  );
}
